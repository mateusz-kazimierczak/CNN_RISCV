#!/usr/bin/env python3
"""Verify the controlled 2x2 to 2x4 Xqmac8 tile comparison and loop accounting."""

from collections import Counter
from copy import deepcopy
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
from tools.xqmac8.analysis import classify
from tools.xqmac8.runtime import digest
from tools.xqmac8.weight_alignment_report import capture, read, require


def artifact(summary, verified, name):
    snapshot = (
        ROOT
        / "build/profiling/compiler"
        / summary["capture_id"]
        / "build_evidence/manifest.json"
    )
    return artifact_path(snapshot, verified[1], name)


def reduction_loops(verified):
    """Count the smallest backward-branch regions containing custom instructions."""
    instructions = verified[4]
    loops = []
    for pc, ins in instructions.items():
        if ins["mnemonic"] not in (
            "bne",
            "beq",
            "blt",
            "bge",
            "bltu",
            "bgeu",
            "c.bnez",
            "c.beqz",
        ):
            continue
        target = re.search(r"(?:^|,)([0-9a-f]+)\s*<", ins["operands"])
        if not target or int(target[1], 16) >= pc:
            continue
        start = int(target[1], 16)
        body = [(a, i) for a, i in sorted(instructions.items()) if start <= a <= pc]
        if any(i["mnemonic"] == "xqmac8" for _, i in body):
            loops.append((start, pc, body))
    inner = [
        l
        for l in loops
        if not any(l[0] <= r[0] and r[1] <= l[1] and r[:2] != l[:2] for r in loops)
    ]
    pcs = {pc for _, _, body in inner for pc, _ in body}
    mix = Counter()
    stack = 0
    for pc in pcs:
        count = verified[6]["histogram"].get(pc, 0)
        mix[classify(instructions[pc]["mnemonic"])] += count
        if "(x2)" in instructions[pc]["operands"]:
            stack += count
    require(
        mix["custom"] == verified[6]["mix"]["custom"],
        "reduction loops do not cover all custom retirements",
    )
    require(stack == 0 and mix["store"] == 0, "stack traffic in a reduction loop")
    event = next(e for u, e in zip(verified[3].units, verified[7]) if u.nodes == (4,))
    sample = next(
        body
        for _, _, body in inner
        if any(i["mnemonic"] == "xqmac8" and pc in event["histogram"] for pc, i in body)
    )
    return {
        "unique_reduction_loops": len(inner),
        "instructions": sum(mix.values()),
        "mix": dict(mix),
        "stack_access_retirements": stack,
        "node4_main_loop": [
            f"{pc:08x}: {i['mnemonic']} {i['operands']}" for pc, i in sample
        ],
        "scope": "union of smallest backward-branch regions containing Xqmac8; custom count reconciles to full inference",
    }


def main():
    verify_files(ROOT, read(ROOT / "tools/compiler/baseline.json")["frozen_files"])
    before, old, _, old_mix, _ = capture("X1-acc64")
    after, new, _, new_mix, _ = capture("X1-tile2x4")
    generated = ROOT / "build/compiler/X1-tile2x4"
    build = verify_build(generated, "rv64")
    require(
        build["binary_sha256"] == after["elf_sha256"], "current ELF/profile mismatch"
    )
    for name in ("constants.cc", "constants.h", "prepared_ir.json"):
        require(
            artifact(before, old, name).read_bytes()
            == artifact(after, new, name).read_bytes(),
            f"constant payload changed: {name}",
        )
    a, b = [
        read(artifact(s, v, "memory_plan.json"))
        for s, v in ((before, old), (after, new))
    ]
    for memory in (a, b):
        memory.pop("kernel_memory_sha256")
    require(a == b, "physical memory plan changed")
    old_plan, new_plan = [
        read(artifact(s, v, "kernel_plan.json"))
        for s, v in ((before, old), (after, new))
    ]
    require(len(old_plan["nodes"]) == len(new_plan["nodes"]), "node inventory changed")
    selected = []
    for a, b in zip(old_plan["nodes"], new_plan["nodes"]):
        normalized = deepcopy(b)
        if a["reduction_backend"].startswith("xqmac8"):
            selected.append(a["node"])
            require(
                a["implementation"].endswith("spatial2_oc2/int8")
                and b["implementation"].endswith("spatial2_oc4/int8"),
                "unexpected tile change",
            )
            require(
                b["geometry"]["output_shape"][-1] % 4 == 0,
                "incomplete output-channel tile",
            )
            normalized["implementation"] = a["implementation"]
            normalized["choices"] = [
                c.replace("output_channel_tile_4", "output_channel_tile_2")
                for c in b["choices"]
            ]
            normalized["memory"]["implementation"] = a["memory"]["implementation"]
            normalized["memory"]["stack_policy"] = normalized["memory"][
                "stack_policy"
            ].replace("fixed 8 scalar", "fixed 4 scalar")
        require(a == normalized, f"nontiling selection changed: node {a['node']}")
    require(len(selected) == 32, "tile coverage incomplete")
    require(old_mix["xqmac8"] == new_mix["xqmac8"] == 42317184, "custom work changed")
    nodes = []
    for a, b in zip(before["units"], after["units"]):
        require(
            a["id"] == b["id"]
            and a["expected_xqmac8_instructions"] == b["expected_xqmac8_instructions"],
            "unit or custom work changed",
        )
        av, bv = [int(x["metrics"]["instructions"]["value"]) for x in (a, b)]
        if a["expected_xqmac8_instructions"]:
            require(bv < av, f"tile regressed: {a['id']}")
            nodes.append(
                {"node": a["nodes"][0], "before": av, "after": bv, "saved": av - bv}
            )
        else:
            require(a["metrics"] == b["metrics"], f"nonpacked node changed: {a['id']}")
    loops = {"before": reduction_loops(old), "after": reduction_loops(new)}
    native = {}
    for kind in ("native", "capture", "sanitized"):
        record = verify_build(generated, kind)
        path = generated / kind / "differential.json"
        proof = read(path)
        require(
            proof["binary_sha256"] == record["binary_sha256"]
            and len(proof["cases"]) == 8,
            "native proof mismatch",
        )
        require(
            all(
                c["status"] == (2 if c["name"] == "zero_point" else 0)
                for c in proof["cases"]
            ),
            "input outcomes changed",
        )
        require(
            kind == "native" or proof["complete_node_arrays_compared"] == 510,
            "incomplete tensor checks",
        )
        native[kind] = {
            "cases": 8,
            "node_arrays": proof["complete_node_arrays_compared"],
            "report_sha256": digest(path),
        }
    outputs = {}
    for case, path in (
        ("baseline", generated / "rv64/spike-verification.json"),
        (
            "random_42",
            ROOT / "build/xqmac8/X1-tile2x4/full-random_42/verification.json",
        ),
    ):
        proof = read(path)
        require(
            proof.get("production_binary_sha256", proof["binary_sha256"])
            == build["binary_sha256"]
            and proof["full_output_bytes_compared"] == 1000,
            "RV64 proof mismatch",
        )
        outputs[case] = {"bytes_compared": 1000, "report_sha256": digest(path)}
    replay, manifest, workload, rows = verify_replay(
        ROOT / "build/compiler/X1-tile2x4-replay/latest.json"
    )
    require(
        workload["nodes"] == [4, 58]
        and len(workload["cases"]) == 8
        and len(rows) == 20
        and set(manifest["kinds"]) == {"native", "sanitized", "rv64"},
        "incomplete replay",
    )
    require(
        read(replay / "build_evidence/manifest.json")["generation"]["artifacts"]
        == new[1]["generation"]["artifacts"],
        "replay/current generation mismatch",
    )
    semantics_path = ROOT / "build/xqmac8/acc64-tests/verification.json"
    semantics = read(semantics_path)
    require(
        semantics["status"] == "PASS"
        and semantics["vectors"] == 10752
        and semantics["schedule_fixtures"] == 72,
        "incomplete register/schedule checks",
    )
    for name, expected in semantics["source_sha256"].items():
        require(digest(ROOT / name) == expected, f"semantic source changed: {name}")
    tests = {}
    for name in ("accumulator_register", "spatial_pointwise"):
        path = ROOT / f"build/xqmac8/tile2x4-{name}-tests.log"
        log = path.read_text()
        match = re.search(r"Ran (\d+) tests? in", log)
        require(
            match and re.search(r"^OK$", log, re.MULTILINE), f"failed tests: {name}"
        )
        tests[name] = {"tests": int(match[1]), "log_sha256": digest(path)}

    def metrics(summary):
        return {
            "capture_id": summary["capture_id"],
            "elf_sha256": summary["elf_sha256"],
            "instructions": int(summary["inference"]["instructions"]["value"]),
            "mix": {k: int(v["value"]) for k, v in summary["inference"]["mix"].items()},
            "footprint": {k: v["value"] for k, v in summary["footprint"].items()},
        }

    saved = int(before["inference"]["instructions"]["value"]) - int(
        after["inference"]["instructions"]["value"]
    )
    code_delta = int(after["footprint"]["executable_code"]["value"]) - int(
        before["footprint"]["executable_code"]["value"]
    )
    result = {
        "schema_version": 1,
        "status": "PASS",
        "configuration": "X1",
        "options": [
            "--pointwise-pixels 2",
            "--pointwise-block 4",
            "--xqmac8-weight-alignment 8",
            "--xqmac8-accumulator-bits 64",
        ],
        "before": metrics(before),
        "after": metrics(after),
        "instructions_saved": saved,
        "instruction_reduction_percent": 100
        * saved
        / int(before["inference"]["instructions"]["value"]),
        "executable_code_growth_bytes": code_delta,
        "nodes": nodes,
        "reduction_loops": loops,
        "native_differential": native,
        "rv64_outputs": outputs,
        "replay": {
            "artifact_id": replay.name,
            "fixtures": len(rows),
            "nodes": [4, 58],
            "input_cases": 8,
        },
        "semantics": {
            "report_sha256": digest(semantics_path),
            "vectors": 10752,
            "chain_length": 64,
            "schedule_fixtures": 72,
        },
        "tests": tests,
        "gates": {
            name: "PASS"
            for name in (
                "only_pointwise_tile_changes",
                "all_32_pointwise_nodes_improve",
                "custom_counts_preserved",
                "no_reduction_loop_stack_traffic",
                "physical_memory_and_constants_preserved",
                "nonpacked_metrics_preserved",
                "repeat_profiles_identical",
                "native_tensor_suite",
                "two_rv64_inputs",
                "replay_all_cases",
                "register_and_schedule_checks",
                "frozen_b0",
            )
        },
        "report_generator_sha256": digest(Path(__file__)),
        "limitations": [
            "Additional executable code and more stores outside reduction loops",
            "Known zero-point Softmax domain outcome is preserved",
            "Spike retirements do not measure hardware cycles or instruction-cache effects",
            "Raw evidence remains in ignored build/ and .deps/",
        ],
    }
    (ROOT / "results/profiling/X1-tile2x4/tiling.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"Xqmac8 tiling gates: PASS; {saved:,} fewer instructions ({result['instruction_reduction_percent']:.2f}%); {code_delta:,} additional code bytes"
    )


if __name__ == "__main__":
    main()
