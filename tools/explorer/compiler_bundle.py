"""Adapt verified compiler captures to the portable single-build evidence contract.

All source bytes come from build snapshots. The working tree is never a fallback.
Weight buffers, generated constants.cc and ELF payloads are intentionally omitted.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from profile_compiler import capture_directory, make_summary, verify_capture
from profile_spike import sha

from compiler.build_evidence import artifact_path, local_file, verify_snapshot


def compiler_context(path):
    from investigation.common import original_root

    path = capture_directory(path)
    manifest, evidence, graph, plan, instructions, syms, invoke, events, residual = (
        verify_capture(path)
    )
    snapshot = path / "build_evidence/manifest.json"
    elf = local_file(
        snapshot.parent, evidence["files"][evidence["build"]["binary"]]["blob"]
    )
    units = []
    for u, event in zip(plan.units, events, strict=True):
        unit = asdict(u)
        unit["nodes"] = [str(n) for n in u.nodes]
        unit["eventIds"] = [str(event["event_id"])]
        unit["source"]["file"] = (
            evidence["artifacts"]["model.cc"]
            if u.source["file"] == "model.cc"
            else u.source["file"]
        )
        for k in ("logical_macs", "executed_products"):
            v = unit["work"].get(k)
            unit["work"][k] = None if v is None else str(v)
        units.append(unit)
    origins = {str(o["node"]): o for o in plan.origins}
    nodes = []
    for n in graph.nodes:
        work = [u.work for u in plan.units if n.index in u.nodes]
        from compiler.execution_plan import reference_work

        estimate = reference_work(graph, n)
        # Executed products belong to an implementation, not to a logical node.
        products = (
            work[0].get("executed_products")
            if len(work) == 1
            and all(len(u.nodes) == 1 for u in plan.units if n.index in u.nodes)
            else None
        )
        nodes.append(
            {
                "id": str(n.index),
                "index": n.index,
                "type": n.kind,
                "group": n.kind,
                "inputs": list(n.source_inputs),
                "outputs": list(n.outputs),
                "unitIds": origins[str(n.index)]["unit_ids"],
                "disposition": origins[str(n.index)]["disposition"],
                "reason": origins[str(n.index)].get("reason"),
                "input_shapes": [list(graph.tensors[t].shape) for t in n.source_inputs],
                "output_shapes": [list(graph.tensors[t].shape) for t in n.outputs],
                "logical_macs": str(estimate["logical_macs"]),
                "executed_products": None if products is None else str(products),
                "options": asdict(n.options),
            }
        )
    tensors = [
        {
            "id": t.index,
            "name": t.name,
            "shape": list(t.shape),
            "type": t.dtype,
            "constant": t.storage == "constant",
            "quantization": None
            if not t.quantization
            else {
                "scales": list(t.quantization.scales),
                "zeroPoints": [str(v) for v in t.quantization.zero_points],
                "axis": t.quantization.quantized_dimension,
            },
            "producer": None if t.producer is None else str(t.producer),
            "consumers": [str(n) for n in t.consumers],
        }
        for t in graph.tensors
    ]
    metadata = {
        "nodes": nodes,
        "tensors": tensors,
        "inputs": list(graph.inputs),
        "outputs": list(graph.outputs),
        "edges": [
            {
                "source": t["producer"],
                "target": c,
                "tensorId": t["id"],
                "id": f"t{t['id']}:{c}",
            }
            for t in tensors
            if t["producer"] is not None
            for c in t["consumers"]
        ],
    }
    fnv = 2166136261
    for byte in (path / "expected-output.bin").read_bytes():
        fnv = ((fnv ^ byte) * 16777619) & 0xFFFFFFFF
    normalized = {
        **manifest,
        "symbols": syms,
        "configuration": plan.configuration,
        "compiler": evidence["build"].get("compiler", "recorded GCC toolchain"),
        "input_seed": manifest["input"]["seed"],
        "output_fnv1a": f"0x{fnv:08x}",
        "hashes": {
            "model": graph.model_sha256,
            "profile_elf": sha(elf),
            "capture": sha(path / "manifest.json"),
            "build_evidence": sha(snapshot),
        },
        "boundaries": manifest["boundary_policy"],
        "repeat_histograms_identical": True,
        "loadable_sections_identical": True,
    }
    memory = json.loads(
        artifact_path(snapshot, evidence, "memory_plan.json").read_text()
    )
    prepared = json.loads(
        artifact_path(snapshot, evidence, "prepared_ir.json").read_text()
    )
    summary = make_summary(
        path,
        (manifest, evidence, graph, plan, instructions, syms, invoke, events, residual),
    )
    metrics = {k: v for k, v in summary["inference"].items() if k != "mix"}
    metrics.update({"mix." + k: v for k, v in summary["inference"]["mix"].items()})
    return {
        "summary": {"inference": metrics, "footprint": summary["footprint"]},
        "manifest": normalized,
        "evidence": evidence,
        "snapshot": snapshot,
        "sourceRoot": original_root(evidence),
        "elf": elf,
        "instructions": instructions,
        "invoke": invoke,
        "ops": events,
        "overhead": sum(residual.values()),
        "graph": metadata,
        "executionPlan": {"units": units},
        "memoryPlan": memory,
        "preparedParameters": prepared,
    }


def saved_source(context, path):
    """Look up a DWARF source identity in the frozen dependency inventory."""
    record = context["evidence"]["files"].get(path)
    if record is None:
        return None
    # Compiler weight payloads are not useful source-navigation evidence.
    if path == context["evidence"]["artifacts"].get("constants.cc"):
        return None
    return local_file(context["snapshot"].parent, record["blob"]).read_bytes()


def attach_analysis(path, context, payloads):
    from investigation.diagnostics import verify_analysis

    directory, data = verify_analysis(path)
    if data["measured_elf_sha256"] != sha(context["elf"]):
        raise ValueError("compiler analysis measured ELF differs from capture")
    analysis_evidence = verify_snapshot(
        directory / "build_evidence/manifest.json", data["build_evidence_sha256"]
    )
    # Same ELF alone is insufficient for provenance: generated plans and sources
    # must agree as well. A newer snapshot may add linker dependencies.
    for name, key in context["evidence"]["artifacts"].items():
        other = analysis_evidence["artifacts"].get(name)
        if (
            other is None
            or context["evidence"]["files"][key]["sha256"]
            != analysis_evidence["files"][other]["sha256"]
        ):
            raise ValueError(
                "compiler analysis generated artifact differs from capture: " + name
            )
    for unit in data["units"]:
        for key, digest in unit["dependency_sha256"].items():
            recorded = context["evidence"]["files"].get(key)
            if recorded and recorded["sha256"] != digest:
                raise ValueError("compiler analysis source dependency mismatch: " + key)
    payloads["compiler/commands.json"] = json.dumps(data["commands"]).encode()
    result = []
    for unit in data["units"]:
        artifacts = []
        for artifact in unit["artifacts"]:
            name = "compiler/" + artifact["path"]
            payloads[name] = local_file(directory, artifact["path"]).read_bytes()
            artifacts.append({**artifact, "archivePath": name})
        result.append(
            {
                "id": unit["id"],
                "source": unit["source"],
                "directory": data["build_root"],
                "arguments": unit["arguments"],
                "baseArguments": unit["base_arguments"],
                "dependencyHashes": unit["dependency_sha256"],
                "artifacts": artifacts,
            }
        )
    return result, {
        "loadableIdentical": True,
        "measuredElfHash": data["measured_elf_sha256"],
        "analysisElfHash": data["analysis_elf_sha256"],
        "commandInventoryPath": "compiler/commands.json",
    }
