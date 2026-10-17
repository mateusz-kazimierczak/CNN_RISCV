"""Construct exact replay fixtures from verified oracle arrays and frozen plans."""

from __future__ import annotations

import hashlib
import json
import struct

from .build_evidence import artifact_path, digest
from .execution_plan import ExecutionPlan, validate_execution_plan, validate_kernel_link
from .ir import Graph
from .oracle import verify_golden

DEFAULT_NODES = (1, 4, 8, 15, 58, 61)


def make_fixtures(snapshot, evidence, oracle, golden, nodes, cases):
    graph = Graph.from_json(
        artifact_path(snapshot, evidence, "graph_ir.json").read_text()
    )
    plan = ExecutionPlan.from_json(
        artifact_path(snapshot, evidence, "execution_plan.json").read_text()
    )
    validate_execution_plan(plan, graph)
    if plan.kernel_plan_sha256:
        if evidence["generation"].get("kernel_plan_sha256") != plan.kernel_plan_sha256:
            raise ValueError("replay generation/kernel plan linkage mismatch")
        validate_kernel_link(
            plan,
            json.loads(
                artifact_path(snapshot, evidence, "kernel_plan.json").read_text()
            ),
        )
    reference = verify_golden(oracle, golden)
    if (
        reference["provenance"]["model_sha256"] != graph.model_sha256
        or reference["provenance"]["tflm_revision"] != graph.reference_revision
    ):
        raise ValueError("replay oracle/model/reference mismatch")
    if (
        not nodes
        or len(set(nodes)) != len(nodes)
        or any(type(n) is not int or n < 0 or n >= len(graph.nodes) for n in nodes)
    ):
        raise ValueError("invalid/duplicate replay node selection")
    if (
        len(set(cases)) != len(cases)
        or not cases
        or not set(cases) <= {c["name"] for c in reference["cases"]}
    ):
        raise ValueError("invalid/duplicate replay input cases")
    memory = json.loads(
        artifact_path(snapshot, evidence, "memory_plan.json").read_text()
    )
    prepared = json.loads(
        artifact_path(snapshot, evidence, "prepared_ir.json").read_text()
    )
    pack = bytearray()
    blobs = {}

    def blob(data):
        sha = hashlib.sha256(data).hexdigest()
        if sha not in blobs:
            pack.extend(bytes((-len(pack)) % 16))
            blobs[sha] = {"offset": len(pack), "bytes": len(data), "sha256": sha}
            pack.extend(data)
        return dict(blobs[sha])

    fixtures = []
    for name in cases:
        case = next(c for c in reference["cases"] if c["name"] == name)
        by_tensor = {t["tensor"]: t for t in case["tensors"]}
        for index in nodes:
            node = graph.nodes[index]
            units = [u for u in plan.units if index in u.nodes]
            if len(units) != 1 or units[0].nodes != (index,):
                raise ValueError(
                    "replay currently requires one A0 unit per selected node"
                )
            inputs = []
            for tid in node.source_inputs:
                if tid < 0 or graph.tensors[tid].storage == "constant":
                    continue
                if tid in graph.inputs:
                    data = (oracle / name / "input.bin").read_bytes()
                elif tid in by_tensor:
                    data = (oracle / name / by_tensor[tid]["file"]).read_bytes()
                else:
                    raise ValueError(
                        f"{name}/node {index}: missing reference input tensor {tid}"
                    )
                if len(data) != graph.tensors[tid].byte_length:
                    raise ValueError("replay tensor byte extent mismatch")
                inputs.append(
                    {
                        "tensor": tid,
                        "arena_offset": memory["tensors"][tid]["offset"],
                        **blob(data),
                    }
                )
            tid = node.outputs[0]
            failure = name == "zero_point" and index == 62
            if failure:
                expected = bytes([0xA7]) * graph.tensors[tid].byte_length
            elif tid in by_tensor:
                expected = (oracle / name / by_tensor[tid]["file"]).read_bytes()
            else:
                raise ValueError(f"{name}/node {index}: no successful reference output")
            output = {
                "tensor": tid,
                "arena_offset": memory["tensors"][tid]["offset"],
                **blob(expected),
            }
            for a in inputs:
                for b in inputs:
                    start = max(a["arena_offset"], b["arena_offset"])
                    end = min(
                        a["arena_offset"] + a["bytes"], b["arena_offset"] + b["bytes"]
                    )
                    if (
                        start < end
                        and pack[
                            a["offset"] + start - a["arena_offset"] : a["offset"]
                            + end
                            - a["arena_offset"]
                        ]
                        != pack[
                            b["offset"] + start - b["arena_offset"] : b["offset"]
                            + end
                            - b["arena_offset"]
                        ]
                    ):
                        raise ValueError("overlapping replay inputs disagree")
            aliases = any(
                a["arena_offset"] < output["arena_offset"] + output["bytes"]
                and output["arena_offset"] < a["arena_offset"] + a["bytes"]
                for a in inputs
            )
            if failure and aliases:
                raise ValueError("error replay requires separate input/output storage")
            fixtures.append(
                {
                    "id": f"{name}/node:{index}",
                    "kind": "kernel",
                    "node": index,
                    "symbol": units[0].symbol,
                    "inputs": inputs,
                    "output": output,
                    "expected_status": 2 if failure else 0,
                    "output_comparison": "unchanged poison bytes"
                    if failure
                    else "complete reference tensor",
                    "aliases_input": aliases,
                    "work": units[0].work,
                }
            )
    # One raw scalar dot-product family, using real node-4/node-58 first-pixel
    # operands and bias. cc_dot includes its existing int64 overflow checks.
    base = next(c for c in reference["cases"] if c["name"] == cases[0])
    by_tensor = {t["tensor"]: t for t in base["tensors"]}
    for index in (4, 58):
        node = graph.nodes[index]
        count = graph.tensors[node.source_inputs[1]].shape[-1]
        input_bytes = (
            oracle / base["name"] / by_tensor[node.source_inputs[0]]["file"]
        ).read_bytes()[:count]
        weights = graph.buffers[graph.tensors[node.source_inputs[1]].buffer].data[
            :count
        ]
        offset = prepared["nodes"][index]["input_offsets"][0]
        bias = graph.constant_values(node.source_inputs[2])[0]
        signed = lambda x: x if x < 128 else x - 256
        expected = (
            sum((signed(x) + offset) * signed(w) for x, w in zip(input_bytes, weights))
            + bias
        )
        if not -(2**31) <= expected < 2**31:
            raise ValueError("microbenchmark accumulator overflows")
        fixtures.append(
            {
                "id": f"scalar_dot/K={count}",
                "kind": "microbenchmark",
                "node": None,
                "symbol": "replay_dot",
                "inputs": [blob(input_bytes), blob(weights)],
                "output": blob(struct.pack("<i", expected)),
                "input_offset": offset,
                "bias": bias,
                "count": count,
                "expected_status": 0,
                "work": {
                    "logical_macs": count,
                    "executed_products": count,
                    "policy": "cc_dot includes int64 accumulator checks",
                    "evidence": "derived",
                },
            }
        )
    return {
        "schema_version": 2,
        "configuration": plan.configuration,
        "fixtures": fixtures,
        "model_sha256": graph.model_sha256,
        "oracle_manifest_sha256": digest(oracle / "manifest.json"),
        "oracle_golden_sha256": digest(golden),
        "cases": list(cases),
        "nodes": list(nodes),
        "fixture_pack_sha256": hashlib.sha256(pack).hexdigest(),
    }, bytes(pack)


def emit_adapter(model_path, generated):
    # Include the original model unchanged in one investigation TU. Its private
    # arena is accessible here; the production model/API never changes.
    return (
        f'#include "{model_path}"\n'
        + """
extern "C" void replay_reset() { reset_input_state(); }
extern "C" uint8_t* replay_arena() { return reinterpret_cast<uint8_t*>(arena.data); }
extern "C" void replay_corrupt_guard() { arena.before[0] ^= 1; }
"""
    )


def emit_fixture_header(workload):
    lines = ["#pragma once", '#include "numerics.h"', 'extern "C" {']
    lines += [
        f"int {symbol}();"
        for symbol in sorted(
            {f["symbol"] for f in workload["fixtures"] if f["kind"] == "kernel"}
        )
    ]
    lines += [
        "}",
        "struct Blob { std::size_t pack, size, arena; };",
        "struct Fixture { int (*entry)(); int status; bool aliases; Blob inputs[3]; unsigned input_count; Blob output; int count, offset, bias; };",
        'extern "C" int replay_dot();',
        "static const Fixture fixtures[] = {",
    ]

    def b(item):
        return (
            "{"
            + f"{item['offset']}, {item['bytes']}, {item.get('arena_offset', 0)}"
            + "}"
        )

    for f in workload["fixtures"]:
        if len(f["inputs"]) > 3:
            raise ValueError("replay input descriptor capacity exceeded")
        inputs = ", ".join(
            [*[b(i) for i in f["inputs"]], *["{}"] * (3 - len(f["inputs"]))]
        )
        lines.append(
            "  {"
            + f"{f['symbol']}, {f['expected_status']}, {'true' if f.get('aliases_input') else 'false'}, {{{inputs}}}, {len(f['inputs'])}, {b(f['output'])}, {f.get('count', 0)}, {f.get('input_offset', 0)}, {f.get('bias', 0)}"
            + "},"
        )
    return "\n".join([*lines, "};", ""])
