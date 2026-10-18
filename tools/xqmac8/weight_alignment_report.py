#!/usr/bin/env python3
"""Revalidate and summarize the controlled X1 packed-weight alignment experiment."""

from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from compiler.build_evidence import artifact_path
from tools.build_a0 import verify_build
from tools.freeze_compiler_baseline import verify_files
from tools.investigation.replay import verify_replay
from tools.profile_compiler import make_summary, verify_capture
from tools.xqmac8.runtime import digest


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def capture(name):
    saved = read(ROOT / f"results/profiling/{name}/summary.json")
    directory = ROOT / "build/profiling/compiler" / saved["capture_id"]
    validated = verify_capture(directory)
    measured = make_summary(directory, validated)
    require(saved == measured, f"{name} summary differs from verified evidence")
    evidence = validated[1]
    snapshot = directory / "build_evidence/manifest.json"
    artifacts = {
        name: artifact_path(snapshot, evidence, name)
        for name in ("kernel_plan.json", "memory_plan.json", "constants.cc")
    }
    mnemonics = Counter()
    for pc, count in validated[6]["histogram"].items():
        mnemonics[validated[4][pc]["mnemonic"]] += count
    instructions = sorted(validated[4].items())
    first = next(
        i for i, (_, ins) in enumerate(instructions) if ins["mnemonic"] == "xqmac8"
    )
    assembly = [
        f"{pc:08x}: {ins['mnemonic']} {ins['operands']}"
        for pc, ins in instructions[max(0, first - 12) : first + 4]
    ]
    return measured, validated, artifacts, dict(mnemonics), assembly


def main():
    verify_files(ROOT, read(ROOT / "tools/compiler/baseline.json")["frozen_files"])
    old, _, old_files, old_mix, old_asm = capture("X1")
    new, new_evidence, new_files, new_mix, new_asm = capture("X1-weights8")
    generated = ROOT / "build/compiler/X1-weights8"
    build = verify_build(generated, "rv64")
    require(new["elf_sha256"] == build["binary_sha256"], "profile/current ELF mismatch")
    previous, current = (
        read(old_files["memory_plan.json"]),
        read(new_files["memory_plan.json"]),
    )
    require(previous["parameters"] == current["parameters"], "prepared constants moved")
    for name in ("arena_bytes", "placements", "scratch", "rodata_bytes"):
        require(previous[name] == current[name], f"memory layout changed: {name}")
    require(
        len(previous["tensors"]) == len(current["tensors"]), "tensor inventory changed"
    )
    for a, b in zip(previous["tensors"], current["tensors"]):
        require(
            all(a[k] == b[k] for k in ("tensor", "offset", "size_bytes", "section")),
            "tensor moved",
        )
    require(
        old_files["constants.cc"].read_bytes()
        == new_files["constants.cc"].read_bytes(),
        "constant payload changed",
    )
    packed = []
    graph = new_evidence[2]
    for node in read(new_files["kernel_plan.json"])["nodes"]:
        if not node["reduction_backend"].startswith("xqmac8"):
            continue
        tid = graph.nodes[node["node"]].input("weights")
        memory = current["tensors"][tid]
        operand = next(o for o in node["memory"]["inputs"] if o["role"] == "weights")
        require(
            operand["alignment"] == memory["alignment"] == 8,
            "weight contract incomplete",
        )
        require(
            memory["offset"] % 8 == node["geometry"]["reduction_depth"] % 8 == 0,
            "weight address/stride proof failed",
        )
        packed.append(node["node"])
    require(
        len(packed) == 32 and current["rodata_alignment"] == 8,
        "packed-node coverage incomplete",
    )
    constants = [s for s in new_evidence[5] if s["name"] == "a0_constants"]
    require(
        len(constants) == 1 and constants[0]["address"] % 8 == 0,
        "linked constants misaligned",
    )
    for a, b in zip(old["units"], new["units"]):
        require(a["id"] == b["id"], "execution units changed")
        if not any(n in packed for n in a["nodes"]):
            require(a["metrics"] == b["metrics"], "nonpacked node changed")
    require(old_mix["xqmac8"] == new_mix["xqmac8"] == 42317184, "custom work changed")
    native = {}
    for kind in ("native", "capture", "sanitized"):
        record = verify_build(generated, kind)
        diff_path = generated / kind / "differential.json"
        diff = read(diff_path)
        require(
            diff["binary_sha256"] == record["binary_sha256"]
            and len(diff["cases"]) == 8,
            "native evidence mismatch",
        )
        require(
            all(
                c["status"] == (2 if c["name"] == "zero_point" else 0)
                for c in diff["cases"]
            ),
            "input outcome changed",
        )
        require(
            kind == "native" or diff["complete_node_arrays_compared"] == 510,
            "incomplete tensor checks",
        )
        native[kind] = {
            "cases": 8,
            "node_arrays": diff["complete_node_arrays_compared"],
            "report_sha256": digest(diff_path),
        }
    outputs = {}
    for case, path in (
        ("baseline", generated / "rv64/spike-verification.json"),
        (
            "random_42",
            ROOT / "build/xqmac8/X1-weights8/full-random_42/verification.json",
        ),
    ):
        proof = read(path)
        require(
            proof.get("production_binary_sha256", proof["binary_sha256"])
            == build["binary_sha256"],
            "output/current ELF mismatch",
        )
        require(proof["full_output_bytes_compared"] == 1000, "incomplete RV64 output")
        outputs[case] = {"bytes_compared": 1000, "report_sha256": digest(path)}
    replay, manifest, workload, rows = verify_replay(
        ROOT / "build/compiler/X1-weights8-replay/latest.json"
    )
    require(
        workload["configuration"] == "X1"
        and workload["nodes"] == [4, 58]
        and len(workload["cases"]) == 8
        and len(rows) == 20,
        "incomplete replay",
    )
    require(
        set(manifest["kinds"]) == {"native", "sanitized", "rv64"},
        "incomplete replay builds",
    )
    replay_evidence = read(replay / "build_evidence/manifest.json")
    require(
        replay_evidence["generation"]["artifacts"]
        == new_evidence[1]["generation"]["artifacts"],
        "replay/current generation mismatch",
    )
    tests = {}
    for name in ("tests", "memory-tests", "kernel-tests", "xqmac-tests"):
        path = ROOT / f"build/xqmac8/weights8-{name}.log"
        log = path.read_text()
        match = re.search(r"Ran (\d+) tests? in", log)
        require(
            match and re.search(r"^OK$", log, re.MULTILINE),
            f"failed regression: {name}",
        )
        tests[name] = {"tests": int(match[1]), "log_sha256": digest(path)}

    def metrics(summary):
        result = {
            k: int(summary["inference"][k]["value"])
            for k in ("instructions", "memory_instructions")
        }
        result.update(
            {
                k: int(summary["inference"]["mix"][k]["value"])
                for k in ("load", "store", "custom")
            }
        )
        result.update(
            {
                k: int(summary["footprint"][k]["value"])
                for k in (
                    "executable_code",
                    "planned_constants_and_parameters",
                    "activation_scratch_workspace",
                )
            }
        )
        return result

    before, after = metrics(old), metrics(new)
    result = {
        "schema_version": 1,
        "status": "PASS",
        "configuration": "X1",
        "option": "--xqmac8-weight-alignment 8",
        "before": {
            "capture_id": old["capture_id"],
            "elf_sha256": old["elf_sha256"],
            **before,
        },
        "after": {
            "capture_id": new["capture_id"],
            "elf_sha256": new["elf_sha256"],
            **after,
        },
        "instructions_saved": before["instructions"] - after["instructions"],
        "instruction_reduction_percent": 100
        * (1 - after["instructions"] / before["instructions"]),
        "packed_nodes": packed,
        "gates": {
            k: "PASS"
            for k in (
                "weight_base_offsets_and_strides",
                "constant_payload_and_offsets_preserved",
                "nonpacked_node_metrics_preserved",
                "full_profile_repeat_identity",
                "custom_counts_reconciled",
                "native_tensor_suite",
                "rv64_two_inputs",
                "replay_all_cases",
                "regressions",
                "frozen_b0_tools",
            )
        },
        "mnemonic_retirements": {"before": old_mix, "after": new_mix},
        "assembly_sample": {"before": old_asm, "after": new_asm},
        "native_differential": native,
        "rv64_outputs": outputs,
        "replay": {
            "artifact_id": replay.name,
            "fixtures": len(rows),
            "nodes": [4, 58],
            "input_cases": 8,
        },
        "tests": tests,
        "report_generator_sha256": digest(Path(__file__)),
        "limitations": [
            "Known zero-point Softmax domain failure is preserved",
            "Spike retirements do not measure hardware cycles",
            "Raw evidence remains under ignored build/ and .deps/",
        ],
    }
    destination = ROOT / "results/profiling/X1-weights8/alignment.json"
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        f"Weight alignment gates: PASS; {result['instructions_saved']:,} fewer instructions ({result['instruction_reduction_percent']:.2f}%)"
    )


if __name__ == "__main__":
    main()
