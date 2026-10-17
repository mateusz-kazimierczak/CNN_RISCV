#!/usr/bin/env python3
"""Capture the exact generated ELF; validate and report from immutable evidence."""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from profile_spike import CATEGORIES, Elf, classify, disassemble, symbols, unique_symbol

from compiler.build_evidence import (
    artifact_path,
    canonical,
    digest,
    local_file,
    open_build,
    verify_snapshot,
)
from compiler.execution_plan import (
    ExecutionPlan,
    reference_work,
    validate_execution_plan,
    validate_kernel_link,
)
from compiler.ir import Graph
from compiler.reference_inputs import CASES

MAX = 2**64 - 1
BOUNDARY = "function entry through returning instruction inclusive; caller call excluded; unit events include callees; input setup, stack painting, verification and printing excluded"
DEFAULT_BUILD = ROOT / "build/compiler/A0/rv64/build.json"


def uint(value):
    if (
        not isinstance(value, (str, int))
        or isinstance(value, bool)
        or not re.fullmatch(r"[0-9]+", str(value))
        or not 0 <= int(value) <= MAX
    ):
        raise ValueError(f"invalid uint64: {value}")
    return int(value)


def metric(value, unit, evidence, scope, **extra):
    return {
        "value": None if value is None else str(value),
        "unit": unit,
        "evidence": evidence,
        "scope": scope,
        **extra,
    }


def ratio(numerator, denominator, unit, scope):
    return {
        "value": None
        if not denominator
        else {"numerator": str(numerator), "denominator": str(denominator)},
        "unit": unit,
        "evidence": "unavailable" if not denominator else "derived",
        "scope": scope,
    }


def read_plan(snapshot, evidence):
    graph = Graph.from_json(
        artifact_path(snapshot, evidence, "graph_ir.json").read_text()
    )
    plan = ExecutionPlan.from_json(
        artifact_path(snapshot, evidence, "execution_plan.json").read_text()
    )
    validate_execution_plan(plan, graph)
    generation = evidence["generation"]
    if generation.get("kernel_plan_sha256") or plan.kernel_plan_sha256:
        if generation.get("kernel_plan_sha256") != plan.kernel_plan_sha256:
            raise ValueError("generation/kernel plan linkage mismatch")
        validate_kernel_link(
            plan,
            json.loads(
                artifact_path(snapshot, evidence, "kernel_plan.json").read_text()
            ),
        )
    if (
        plan.configuration != evidence["build"]["configuration"]
        or plan.prepared_ir_sha256 != generation["prepared_ir_sha256"]
        or plan.memory_plan_sha256 != generation["memory_plan_sha256"]
        or graph.model_sha256 != generation["model_sha256"]
    ):
        raise ValueError("execution plan/build linkage mismatch")
    return graph, plan


def resolve_boundaries(elf, plan):
    syms = symbols(elf)
    instructions = disassemble(elf)
    text = Elf(elf).sections[".text"]
    root = unique_symbol(syms, plan.inference_symbol)
    units = []
    probes = {}
    for unit in plan.units:
        entry = unique_symbol(syms, unit.symbol)
        if entry == root:
            raise ValueError(
                "unit and invocation entry alias; cannot distinguish scopes"
            )
        probes[entry] = f"probe_{entry:x}"
        units.append({"unit_id": unit.id, "entry": entry, "probe": probes[entry]})
    if any(pc not in instructions for pc in (root, *probes)):
        raise ValueError("profile symbol is not a decoded instruction")
    lines = [
        f"code {text['address']:#x} {text['address'] + text['size']:#x}",
        f"region invoke {root:#x}",
    ]
    lines += [f"operator {name} {pc:#x}" for pc, name in sorted(probes.items())]
    return {"root": root, "units": units}, "\n".join(lines) + "\n", instructions, syms


def load_capture(prefix, boundaries, instructions):
    with Path(str(prefix) + ".events.csv").open() as f:
        events = list(csv.DictReader(f))
    expected = [("region", "invoke", boundaries["root"])] + [
        ("operator", u["probe"], u["entry"]) for u in boundaries["units"]
    ]
    if len(events) != len(expected):
        raise ValueError("event coverage differs from execution schedule")
    for index, (event, (kind, name, entry)) in enumerate(zip(events, expected)):
        for key in (
            "event_id",
            "entry",
            "return_pc",
            "complete",
            "status",
            "total",
            "faulted",
        ):
            event[key] = uint(event[key])
        if (
            event["event_id"] != index
            or (event["kind"], event["name"], event["entry"]) != (kind, name, entry)
            or event["complete"] != 1
            or event["status"] != 0
            or event["faulted"] != 0
            or event["total"] == 0
            or event["return_pc"] not in instructions
        ):
            raise ValueError(f"invalid/incomplete/unexpected event: {index}")
        event["histogram"] = {}
        event["mix"] = dict.fromkeys(CATEGORIES, 0)
    with Path(str(prefix) + ".pcs.csv").open() as f:
        for row in csv.DictReader(f):
            eid, pc, bits, length, count = (
                uint(row[k]) for k in ("event_id", "pc", "bits", "length", "count")
            )
            if eid >= len(events) or not count:
                raise ValueError("invalid histogram identity/count")
            event, ins = events[eid], instructions.get(pc)
            if (
                not ins
                or (bits, length) != (ins["bits"], ins["length"])
                or pc in event["histogram"]
            ):
                raise ValueError("duplicate, mismatched or undecodable PC")
            event["histogram"][pc] = count
            event["mix"][classify(ins["mnemonic"])] += count
    for event in events:
        if (
            sum(event["histogram"].values()) != event["total"]
            or sum(event["mix"].values()) != event["total"]
            or not event["histogram"].get(event["entry"])
        ):
            raise ValueError("event histogram/mix/entry does not reconcile")
    residual = dict(events[0]["histogram"])
    for event in events[1:]:
        for pc, count in event["histogram"].items():
            residual[pc] = residual.get(pc, 0) - count
            if residual[pc] < 0:
                raise ValueError("execution units exceed invocation at a PC")
    if (
        sum(residual.values()) + sum(e["total"] for e in events[1:])
        != events[0]["total"]
    ):
        raise ValueError("invocation partition does not reconcile")
    return events[0], events[1:], {pc: n for pc, n in residual.items() if n}


def check_output(text, expected, configuration="A0"):
    lines = text.replace("\r", "").splitlines()
    if (
        f"{configuration} EfficientNet-Lite0 inference: PASS" not in lines
        or "output_top_index=21 output_top_score=48 output_sum=215" not in lines
        or "output_fnv1a=0x4b6a91e2" not in lines
    ):
        raise ValueError("target failed its configuration/baseline/guard checks")
    outputs = [
        line.removeprefix("output_hex=")
        for line in lines
        if line.startswith("output_hex=")
    ]
    if (
        len(outputs) != 1
        or not re.fullmatch(r"[0-9a-f]{2000}", outputs[0])
        or bytes.fromhex(outputs[0]) != expected
    ):
        raise ValueError("complete 1,000-byte public output mismatch")


def capture_directory(path):
    path = Path(path).resolve()
    if path.name == "latest.json" and path.is_file():
        identity = json.loads(path.read_text())["capture_id"]
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("invalid capture pointer")
        return path.parent / identity
    return path.parent if path.name == "manifest.json" else path


def verify_capture(directory):
    directory = capture_directory(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if (
        manifest.get("schema_version") != 2
        or manifest.get("format") != "compiler-spike-capture"
    ):
        raise ValueError("unsupported compiler capture schema")
    if directory.name != digest(directory / "manifest.json"):
        raise ValueError("capture is not its content-addressed identity")
    actual = {
        str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()
    } - {"manifest.json"}
    if actual != set(manifest["files"]):
        raise ValueError("capture file inventory differs from manifest")
    for name, record in manifest["files"].items():
        path = local_file(directory, name)
        if digest(path) != record["sha256"] or path.stat().st_size != record["size"]:
            raise ValueError(f"capture artifact changed: {name}")
    snapshot = directory / "build_evidence/manifest.json"
    evidence = verify_snapshot(snapshot, manifest["build_evidence_sha256"])
    graph, plan = read_plan(snapshot, evidence)
    elf = local_file(
        snapshot.parent, evidence["files"][evidence["build"]["binary"]]["blob"]
    )
    boundaries, config, instructions, syms = resolve_boundaries(elf, plan)
    if (
        boundaries != manifest["boundaries"]
        or config != (directory / "regions.txt").read_text()
    ):
        raise ValueError("capture boundaries disagree with linked execution plan")
    if (
        manifest["configuration"] != plan.configuration
        or manifest["model_sha256"] != graph.model_sha256
    ):
        raise ValueError("capture configuration/model mismatch")
    expected = (directory / "expected-output.bin").read_bytes()
    if (
        len(expected) != 1000
        or digest(directory / "expected-output.bin") != manifest["output_sha256"]
    ):
        raise ValueError("invalid reference output")
    golden = json.loads((directory / "oracle-golden.json").read_text())
    if (
        golden["model_sha256"] != graph.model_sha256
        or golden["cases"][0]["output_sha256"] != manifest["output_sha256"]
        or golden["cases"][0]["input_sha256"] != manifest["input"]["sha256"]
    ):
        raise ValueError("reference output is not the frozen oracle result")
    if (
        manifest["input"] != evidence["build"]["workload"]
        or digest(directory / "input.bin") != manifest["input"]["sha256"]
        or manifest["input"]["case"] != "baseline"
        or manifest["input"]["seed"] != 1
        or manifest["boundary_policy"] != BOUNDARY
    ):
        raise ValueError("input/boundary contract changed")
    for repeat in (1, 2):
        check_output(
            (directory / f"run{repeat}-output.txt").read_text(),
            expected,
            plan.configuration,
        )
    check_output(
        (directory / "ordinary-output.txt").read_text(), expected, plan.configuration
    )
    for suffix in ("events.csv", "pcs.csv"):
        if (directory / f"run1.{suffix}").read_bytes() != (
            directory / f"run2.{suffix}"
        ).read_bytes():
            raise ValueError("repeated captures differ")
    invocation, units, residual = load_capture(
        directory / "run1", boundaries, instructions
    )
    return (
        manifest,
        evidence,
        graph,
        plan,
        instructions,
        syms,
        invocation,
        units,
        residual,
    )


def freeze_b0(destination):
    contract = json.loads((ROOT / "tools/compiler/baseline.json").read_text())
    path = ROOT / "results/profiling/B0/summary.json"
    frozen = contract["frozen_files"]
    # The Stage 0 contract pins the entire compact baseline report.
    expected = frozen["results/profiling/B0/summary.json"]
    if isinstance(expected, dict):
        expected = expected["sha256"]
    if digest(path) != expected:
        raise ValueError("B0 summary differs from frozen Stage 0 evidence")
    data = json.loads(path.read_text())
    if data["inference"]["instructions"] != contract["inference_instructions"]:
        raise ValueError("B0 instruction total changed")
    shutil.copyfile(path, destination / "B0-summary.json")
    shutil.copyfile(
        ROOT / "tools/compiler/baseline.json", destination / "B0-contract.json"
    )


def run_profile(args):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", args.checkpoint):
        raise ValueError("checkpoint must be a simple label")
    snapshot, evidence = open_build(args.build_manifest.resolve())
    if evidence["build"]["kind"] != "rv64" or evidence["build"][
        "configuration"
    ] not in ("A0", "B1"):
        raise ValueError(
            "this adapter requires an actual RV64 A0/B1 build, not a configuration label"
        )
    graph, plan = read_plan(snapshot, evidence)
    original = local_file(
        snapshot.parent, evidence["files"][evidence["build"]["binary"]]["blob"]
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".capture-", dir=args.output_root
    ) as temporary:
        staged = Path(temporary) / "capture"
        staged.mkdir()
        shutil.copytree(snapshot.parent, staged / "build_evidence")
        # Use exactly the same saved ELF for ordinary execution and both captures.
        elf = (
            staged
            / "build_evidence"
            / evidence["files"][evidence["build"]["binary"]]["blob"]
        )
        if digest(elf) != digest(original):
            raise ValueError("ELF changed while staging")
        boundaries, config, instructions, _ = resolve_boundaries(elf, plan)
        (staged / "regions.txt").write_text(config)
        expected = ROOT / "tests/compiler/fixtures/baseline-output.bin"
        golden = json.loads(
            (ROOT / "tests/compiler/fixtures/oracle-golden.json").read_text()
        )
        if (
            digest(expected) != golden["cases"][0]["output_sha256"]
            or golden["model_sha256"] != graph.model_sha256
        ):
            raise ValueError("baseline fixture/model mismatch")
        shutil.copyfile(expected, staged / "expected-output.bin")
        shutil.copyfile(
            ROOT / "tests/compiler/fixtures/oracle-golden.json",
            staged / "oracle-golden.json",
        )
        (staged / "input.bin").write_bytes(CASES[0].data())
        if evidence["build"]["workload"] != {
            "case": "baseline",
            "seed": 1,
            "sha256": digest(staged / "input.bin"),
        }:
            raise ValueError("build workload differs from canonical input")
        freeze_b0(staged)
        if args.parent:
            parent_dir = capture_directory(args.parent)
            parent = verify_capture(parent_dir)
            if parent[0]["model_sha256"] != graph.model_sha256:
                raise ValueError("parent model differs")
            (staged / "parent-summary.json").write_text(
                canonical(make_summary(parent_dir, parent))
            )
            (staged / "parent-identity.txt").write_text(
                digest(parent_dir / "manifest.json") + "\n"
            )
        ordinary = ROOT / ".deps/spike/bin/spike"
        collector = ROOT / ".deps/spike-profile/bin/spike"
        collector_identity = {
            "binary_sha256": digest(collector),
            "ordinary_binary_sha256": digest(ordinary),
            "patch_sha256": digest(ROOT / "tools/spike_profile/spike.patch"),
            "header_sha256": digest(ROOT / "tools/spike_profile/roi_profiler.h"),
            "adapter_sha256": digest(Path(__file__)),
        }
        for name in (
            "tools/spike_profile/spike.patch",
            "tools/spike_profile/roi_profiler.h",
            "tools/profile_compiler.py",
            "tools/profile_spike.py",
        ):
            target = staged / "collector_sources" / Path(name).name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        commands = []
        for repeat in (0, 1, 2):
            command = [str(ordinary if repeat == 0 else collector), "--isa=rv64imc"]
            if repeat:
                command += [
                    f"--profile-config={staged / 'regions.txt'}",
                    f"--profile-output={staged / f'run{repeat}'}",
                ]
            command.append(str(elf))
            print(
                f"{plan.configuration} {args.checkpoint}: {'ordinary verification' if not repeat else f'profile {repeat}/2'}",
                flush=True,
            )
            result = subprocess.run(
                command, text=True, capture_output=True, timeout=1800, check=True
            )
            stem = "ordinary" if not repeat else f"run{repeat}"
            (staged / f"{stem}-output.txt").write_text(result.stdout.replace("\r", ""))
            (staged / f"{stem}-stderr.txt").write_text(result.stderr)
            check_output(result.stdout, expected.read_bytes(), plan.configuration)
            if repeat:
                load_capture(staged / f"run{repeat}", boundaries, instructions)
            commands.append([v.replace(str(staged), "<capture>") for v in command])
        if (
            digest(collector) != collector_identity["binary_sha256"]
            or digest(ordinary) != collector_identity["ordinary_binary_sha256"]
        ):
            raise ValueError("simulator changed during capture")
        for suffix in ("events.csv", "pcs.csv"):
            if (staged / f"run1.{suffix}").read_bytes() != (
                staged / f"run2.{suffix}"
            ).read_bytes():
                raise ValueError("repeated captures differ")
        files = {
            str(p.relative_to(staged)): {"sha256": digest(p), "size": p.stat().st_size}
            for p in sorted(staged.rglob("*"))
            if p.is_file()
        }
        manifest = {
            "format": "compiler-spike-capture",
            "schema_version": 2,
            "configuration": plan.configuration,
            "checkpoint": args.checkpoint,
            "model_sha256": graph.model_sha256,
            "build_evidence_sha256": digest(staged / "build_evidence/manifest.json"),
            "input": {
                "case": "baseline",
                "seed": 1,
                "sha256": hashlib.sha256(CASES[0].data()).hexdigest(),
            },
            "output_sha256": digest(expected),
            "boundary_policy": BOUNDARY,
            "boundaries": boundaries,
            "collector": collector_identity,
            "commands": commands,
            "files": files,
        }
        (staged / "manifest.json").write_text(canonical(manifest))
        identity = digest(staged / "manifest.json")
        destination = args.output_root / identity
        if destination.exists():
            verify_capture(destination)
        else:
            staged.rename(destination)
    report(
        destination, args.results_dir or ROOT / "results/profiling" / args.checkpoint
    )
    # Convenience pointer; never a substitute for the content identity.
    (args.output_root / "latest.json").write_text(
        canonical({"capture_id": identity, "checkpoint": args.checkpoint})
    )
    print(f"Validated capture: {destination}", flush=True)


def event_metrics(event, scope, work=None):
    work = work or {}
    result = {
        "instructions": metric(
            event["total"], "retired_instructions", "measured", scope
        )
    }
    result["mix"] = {
        c: metric(n, "retired_instructions", "measured", scope)
        for c, n in event["mix"].items()
    }
    memory = event["mix"]["load"] + event["mix"]["store"]
    result["memory_instructions"] = metric(
        memory, "retired_instructions", "measured", scope
    )
    for key in ("logical_macs", "executed_products"):
        value = work.get(key)
        result[key] = metric(
            value,
            "products",
            "derived" if value is not None else "unavailable",
            scope,
            policy=work.get("policy"),
        )
        result[key + "_per_instruction"] = ratio(
            value or 0,
            event["total"] if value is not None else 0,
            "products/retired_instruction",
            scope,
        )
    result["memory_instructions_per_executed_product"] = ratio(
        memory, work.get("executed_products"), "memory_instructions/product", scope
    )
    result["custom_frequency"] = ratio(
        event["mix"]["custom"],
        event["total"],
        "custom_instructions/retired_instruction",
        scope,
    )
    return result


def function_counts(event, instructions, syms):
    ranges = [s for s in syms if s["kind"] in "tTW" and s["size"]]
    counts = collections.Counter()
    for pc, n in event["histogram"].items():
        candidates = [
            s for s in ranges if s["address"] <= pc < s["address"] + s["size"]
        ]
        function = (
            min(candidates, key=lambda s: (s["size"], s["name"]))["name"]
            if candidates
            else "<unattributed>"
        )
        counts[function] += n
    return [
        {
            "function": name,
            "instructions": metric(
                n, "retired_instructions", "measured", "exclusive_function_body"
            ),
        }
        for name, n in counts.most_common()
    ]


def make_summary(directory, validated=None):
    directory = capture_directory(directory)
    (
        manifest,
        evidence,
        graph,
        plan,
        instructions,
        syms,
        invocation,
        events,
        residual,
    ) = validated or verify_capture(directory)
    snapshot = directory / "build_evidence/manifest.json"
    memory = json.loads(
        artifact_path(snapshot, evidence, "memory_plan.json").read_text()
    )
    values = [u.work.get("executed_products") for u in plan.units]
    work = {
        "logical_macs": sum(
            reference_work(graph, n)["logical_macs"] for n in graph.nodes
        ),
        "executed_products": sum(values)
        if all(v is not None for v in values)
        else None,
        "policy": "sum of compiler-declared execution-unit schedules; logical MACs from graph",
    }
    units = [
        {
            "id": unit.id,
            "nodes": list(unit.nodes),
            "symbol": unit.symbol,
            "implementation": unit.implementation,
            "notes": list(unit.notes),
            "metrics": event_metrics(event, "inclusive_execution_unit", unit.work),
        }
        for unit, event in zip(plan.units, events)
    ]
    overhead = {"total": sum(residual.values()), "mix": dict.fromkeys(CATEGORIES, 0)}
    for pc, count in residual.items():
        overhead["mix"][classify(instructions[pc]["mnemonic"])] += count
    elf = Elf(
        local_file(
            snapshot.parent, evidence["files"][evidence["build"]["binary"]]["blob"]
        )
    )
    footprint = {
        "executable_code": metric(
            sum(s["size"] for s in elf.sections.values() if s["flags"] & 6 == 6),
            "bytes",
            "derived",
            "allocated_executable_sections",
        ),
        "readonly": metric(
            sum(
                s["size"]
                for s in elf.sections.values()
                if s["flags"] & 2 and not s["flags"] & 5
            ),
            "bytes",
            "derived",
            "allocated_readonly_sections",
        ),
        "bss": metric(
            sum(
                s["size"]
                for s in elf.sections.values()
                if s["flags"] & 2 and s["type"] == 8
            ),
            "bytes",
            "derived",
            "allocated_nobits_sections",
        ),
        "initialized_writable": metric(
            sum(
                s["size"]
                for s in elf.sections.values()
                if s["flags"] & 3 == 3 and s["type"] != 8
            ),
            "bytes",
            "derived",
            "allocated_writable_sections",
        ),
        "activation_scratch_workspace": metric(
            memory["arena_bytes"], "bytes", "derived", "static_memory_plan"
        ),
        "planned_constants_and_parameters": metric(
            memory["rodata_bytes"], "bytes", "derived", "static_memory_plan"
        ),
        "peak_live_activations": metric(
            memory["summary"]["peak_live_activation_bytes"],
            "bytes",
            "derived",
            "static_memory_plan",
        ),
        "hardware_cycles": metric(None, "cycles", "unavailable", "CV-Wally"),
    }
    comparisons = []
    b0 = json.loads((directory / "B0-summary.json").read_text())
    if (
        b0["provenance"]["hashes"]["model"] != graph.model_sha256
        or b0["provenance"]["input_seed"] != manifest["input"]["seed"]
    ):
        raise ValueError("B0 comparison model/input differs")
    comparisons.append(
        compare_summary(
            b0["configuration"],
            b0["inference"]["instructions"],
            {str(n["index"]): n["instructions"] for n in b0["layers"]},
            invocation["total"],
            units,
        )
    )
    if (directory / "parent-summary.json").exists():
        parent = json.loads((directory / "parent-summary.json").read_text())
        if (
            parent["model_sha256"] != graph.model_sha256
            or parent["input"] != manifest["input"]
            or parent["boundary_policy"] != BOUNDARY
        ):
            raise ValueError("parent input/model/scope differs")
        comparisons.append(
            compare_summary(
                parent["checkpoint"],
                uint(parent["inference"]["instructions"]["value"]),
                logical_node_counts(parent["units"]),
                invocation["total"],
                units,
            )
        )
    return {
        "schema_version": 2,
        "configuration": plan.configuration,
        "checkpoint": manifest["checkpoint"],
        "capture_id": directory.name,
        "model_sha256": graph.model_sha256,
        "input": manifest["input"],
        "elf_sha256": evidence["build"]["binary_sha256"],
        "build_evidence_sha256": manifest["build_evidence_sha256"],
        "report_generator_sha256": digest(Path(__file__)),
        "boundary_policy": BOUNDARY,
        "inference": event_metrics(invocation, "full_inference", work),
        "overhead": event_metrics(overhead, "invocation_outside_execution_units"),
        "allocation": None,
        "units": units,
        "functions": function_counts(invocation, instructions, syms),
        "top_pcs": [
            {
                "pc": str(pc),
                "bits": hex(instructions[pc]["bits"]),
                "mnemonic": instructions[pc]["mnemonic"],
                "operands": instructions[pc]["operands"],
                "instructions": metric(
                    n, "retired_instructions", "measured", "exclusive_PC"
                ),
            }
            for pc, n in sorted(
                invocation["histogram"].items(), key=lambda pair: (-pair[1], pair[0])
            )[:30]
        ],
        "footprint": footprint,
        "comparisons": comparisons,
        "gates": {
            "repeat_histograms_identical": True,
            "per_pc_partition": True,
            "full_output_bytes_compared": 1000,
            "observed_execution_units": len(events),
        },
        "limitations": [
            "Spike retirements are not CV-Wally cycles.",
            "Memory instructions are not DRAM traffic or cache misses.",
            "AOT workspace and LiteRT total arena have different accounting.",
            "Softmax domain preflight and existing wrapper costs remain inside inference.",
            "Known all-zero-point input fails Softmax; canonical performance input is seed 1.",
        ],
    }


def logical_node_counts(units):
    counts = collections.Counter()
    shared = set()
    for unit in units:
        if len(unit["nodes"]) == 1:
            counts[str(unit["nodes"][0])] += uint(
                unit["metrics"]["instructions"]["value"]
            )
        else:
            shared.update(map(str, unit["nodes"]))
    return {node: n for node, n in counts.items() if node not in shared}


def compare_summary(name, before, old_nodes, after, units):
    rows = []
    for node, current in sorted(
        logical_node_counts(units).items(), key=lambda p: int(p[0])
    ):
        if node not in old_nodes:
            continue
        prior = old_nodes[node]
        rows.append(
            {
                "node": int(node),
                "before": str(prior),
                "after": str(current),
                "delta": str(current - prior),
            }
        )
    return {
        "reference": name,
        "scope": "equivalent full invocation; inclusive logical-node costs where uniquely measurable",
        "unit": "retired_instructions",
        "evidence": "derived",
        "before": str(before),
        "after": str(after),
        "delta": str(after - before),
        "instruction_count_ratio": {
            "numerator": str(before),
            "denominator": str(after),
        },
        "nodes": rows,
    }


def report(directory, output):
    directory, output = capture_directory(directory), Path(output)
    if output.resolve().is_relative_to(directory.resolve()):
        raise ValueError("report output cannot modify an immutable capture")
    result = make_summary(directory)
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(canonical(result))
    with (output / "units.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "unit_id",
                "original_nodes",
                "symbol",
                "instructions",
                "logical_macs",
                "executed_products",
                *CATEGORIES,
            ]
        )
        for unit in result["units"]:
            m = unit["metrics"]
            writer.writerow(
                [
                    unit["id"],
                    " ".join(map(str, unit["nodes"])),
                    unit["symbol"],
                    m["instructions"]["value"],
                    m["logical_macs"]["value"],
                    m["executed_products"]["value"],
                    *[m["mix"][c]["value"] for c in CATEGORIES],
                ]
            )
    total = uint(result["inference"]["instructions"]["value"])
    lines = [
        f"# {result['checkpoint']}: {result['configuration']} instruction profile",
        "",
        f"Full inference: **{total:,} retired instructions**. Allocation is absent.",
        f"Execution units: {len(result['units'])}; invocation overhead: {uint(result['overhead']['instructions']['value']):,} instructions.",
        "Two event/PC captures match exactly; all 1,000 output bytes match the reference.",
        "",
        f"Capture: `{directory.name}`; ELF: `{result['elf_sha256']}`.",
        "",
        "## Comparisons",
        "",
        "| Reference | Before | After | Change | Instruction-count ratio |",
        "|---|---:|---:|---:|---:|",
    ]
    for c in result["comparisons"]:
        lines.append(
            f"| {c['reference']} | {int(c['before']):,} | {int(c['after']):,} | {int(c['delta']):+,} | {int(c['before']) / int(c['after']):.6f}× |"
        )
    lines += [
        "",
        "Ratios describe retired instructions, not timing speedup. Per-node comparisons are in summary.json.",
        "",
        "## Footprint",
        "",
    ]
    lines += [
        f"- {key}: {value['value']} {value['unit']} ({value['evidence']}; {value['scope']})."
        for key, value in result["footprint"].items()
    ]
    lines += [
        "",
        "## Largest inclusive execution units",
        "",
        "| Node(s) | Implementation | Instructions |",
        "|---|---|---:|",
    ]
    lines += [
        f"| {','.join(map(str, u['nodes']))} | {u['implementation']} | {uint(u['metrics']['instructions']['value']):,} |"
        for u in sorted(
            result["units"], key=lambda u: -uint(u["metrics"]["instructions"]["value"])
        )[:10]
    ]
    lines += ["", "## Limits", "", *["- " + s for s in result["limitations"]], ""]
    (output / "README.md").write_text("\n".join(lines))
    print(
        f"Validated {result['checkpoint']}: {total:,} instructions; {len(result['units'])} units; report {output}",
        flush=True,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--build-manifest", type=Path, default=DEFAULT_BUILD)
    run.add_argument("--checkpoint", required=True)
    run.add_argument("--parent", type=Path)
    run.add_argument(
        "--output-root", type=Path, default=ROOT / "build/profiling/compiler"
    )
    run.add_argument("--results-dir", type=Path)
    saved = commands.add_parser("report")
    saved.add_argument("--capture", type=Path, required=True)
    saved.add_argument("--output", type=Path, required=True)
    replay_command = commands.add_parser("replay")
    replay_command.add_argument("--build-manifest", type=Path, default=DEFAULT_BUILD)
    replay_command.add_argument(
        "--host-build-manifest",
        type=Path,
        default=ROOT / "build/compiler/A0/native/build.json",
    )
    replay_command.add_argument("--oracle", type=Path)
    replay_command.add_argument(
        "--golden",
        type=Path,
        default=ROOT / "tests/compiler/fixtures/oracle-golden.json",
    )
    replay_command.add_argument("--nodes", default="1,4,8,15,58,61")
    replay_command.add_argument("--cases", default="baseline")
    replay_command.add_argument("--kinds", default="native,sanitized,rv64")
    replay_command.add_argument(
        "--output-root", type=Path, default=ROOT / "build/compiler/replay"
    )
    replay_command.add_argument(
        "--results-dir", type=Path, default=ROOT / "results/profiling/A0-replay"
    )
    analysis_command = commands.add_parser("analyze")
    analysis_command.add_argument("--build-manifest", type=Path, default=DEFAULT_BUILD)
    analysis_command.add_argument(
        "--output-root", type=Path, default=ROOT / "build/compiler/gcc-analysis"
    )
    analysis_command.add_argument(
        "--results-dir", type=Path, default=ROOT / "results/profiling/A0-gcc"
    )
    export_command = commands.add_parser("export")
    export_command.add_argument("--capture", type=Path, required=True)
    export_command.add_argument("--compiler-analysis", type=Path)
    export_command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "export":
            from export_explorer import export_bundle

            export_bundle(
                args.capture,
                None,
                None,
                args.output,
                args.compiler_analysis,
                compiler_capture=True,
            )
        elif args.command == "run":
            run_profile(args)
        elif args.command == "analyze":
            from investigation.diagnostics import analyze

            analyze(args)
        elif args.command == "replay":
            from investigation.replay import replay

            args.nodes = [int(n) for n in args.nodes.split(",")]
            args.cases = (
                [c.name for c in CASES]
                if args.cases == "all"
                else args.cases.split(",")
            )
            args.kinds = args.kinds.split(",")
            if (
                not args.kinds
                or len(set(args.kinds)) != len(args.kinds)
                or not set(args.kinds) <= {"native", "sanitized", "rv64"}
            ):
                raise ValueError("invalid replay build kinds")
            if args.oracle is None:
                args.oracle = Path(
                    json.loads(
                        (ROOT / "build/compiler/oracle/latest.json").read_text()
                    )["capture"]
                )
            replay(args)
        else:
            selected = args.capture
            if selected.name == "latest.json" and "artifact_id" in json.loads(
                selected.read_text()
            ):
                from investigation.common import archive_path

                selected = archive_path(selected)
            capture_manifest = json.loads(
                (capture_directory(selected) / "manifest.json").read_text()
            )
            if (
                capture_manifest
                and capture_manifest.get("format") == "compiler-kernel-replay"
            ):
                from investigation.replay import report as replay_report

                replay_report(selected, args.output)
            elif capture_manifest.get("format") == "compiler-gcc-analysis":
                from investigation.diagnostics import report as analysis_report

                analysis_report(selected, args.output)
            else:
                report(args.capture, args.output)
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stdout, error.stderr, file=sys.stderr)
        parser.exit(1, f"Compiler profile failed: {error}\n")


if __name__ == "__main__":
    main()
