#!/usr/bin/env python3
"""Revalidate the X1 accumulator-register experiment against aligned-weight X1."""

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
from tools.profile_spike import Elf
from tools.xqmac8.runtime import digest
from tools.xqmac8.weight_alignment_report import capture, read, require


def zero_extensions(verified):
    return sum(
        verified[6]["histogram"].get(pc, 0)
        for pc, ins in verified[4].items()
        if ins["mnemonic"] in ("c.addiw", "addiw") and ins["operands"].endswith(",0")
    )


def main():
    verify_files(ROOT, read(ROOT / "tools/compiler/baseline.json")["frozen_files"])
    before, old, old_files, old_mix, old_asm = capture("X1-weights8")
    after, new, new_files, new_mix, new_asm = capture("X1-acc64")
    generated = ROOT / "build/compiler/X1-acc64"
    build = verify_build(generated, "rv64")
    require(
        after["elf_sha256"] == build["binary_sha256"], "current/profile ELF mismatch"
    )
    for name in ("memory_plan.json", "constants.cc", "constants.h", "prepared_ir.json"):
        a = artifact_path(
            ROOT
            / "build/profiling/compiler"
            / before["capture_id"]
            / "build_evidence/manifest.json",
            old[1],
            name,
        )
        b = artifact_path(
            ROOT
            / "build/profiling/compiler"
            / after["capture_id"]
            / "build_evidence/manifest.json",
            new[1],
            name,
        )
        require(
            a.read_bytes() == b.read_bytes(), f"memory or prepared data changed: {name}"
        )
    require(old_mix["xqmac8"] == new_mix["xqmac8"] == 42317184, "custom work changed")
    for a, b in zip(before["units"], after["units"]):
        require(a["id"] == b["id"], "unit identity changed")
        if not a["expected_xqmac8_instructions"]:
            require(a["metrics"] == b["metrics"], "nonpacked node metrics changed")
    controls = {}
    for label, reference, candidate in (
        ("B1", "B1-spatial2-oc2", "B1-acc64-control"),
        ("X1-weights8", "X1-weights8", "X1-acc32-control"),
    ):
        verify_build(ROOT / "build/compiler" / candidate, "rv64")
        paths = [
            ROOT / "build/compiler" / name / "rv64/a0.elf"
            for name in (reference, candidate)
        ]
        a, b = map(Elf, paths)
        require(
            a.allocated() == b.allocated() and a.loads == b.loads,
            f"legacy bytes changed: {label}",
        )
        controls[label] = {
            "reference_elf_sha256": digest(paths[0]),
            "control_elf_sha256": digest(paths[1]),
            "allocated_sections_identical": True,
            "load_segments_identical": True,
        }
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
            "native outcome changed",
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
        ("random_42", ROOT / "build/xqmac8/X1-acc64/full-random_42/verification.json"),
    ):
        proof = read(path)
        require(
            proof.get("production_binary_sha256", proof["binary_sha256"])
            == build["binary_sha256"]
            and proof["full_output_bytes_compared"] == 1000,
            "RV64 output mismatch",
        )
        outputs[case] = {"bytes_compared": 1000, "report_sha256": digest(path)}
    replay, manifest, workload, rows = verify_replay(
        ROOT / "build/compiler/X1-acc64-replay/latest.json"
    )
    require(
        workload["nodes"] == [4, 58]
        and len(workload["cases"]) == 8
        and len(rows) == 20
        and set(manifest["kinds"]) == {"native", "sanitized", "rv64"},
        "replay coverage incomplete",
    )
    require(
        read(replay / "build_evidence/manifest.json")["generation"]["artifacts"]
        == new[1]["generation"]["artifacts"],
        "replay/generation mismatch",
    )
    semantics_path = ROOT / "build/xqmac8/acc64-tests/verification.json"
    semantics = read(semantics_path)
    require(
        semantics["status"] == "PASS"
        and semantics["vectors"] == 10752
        and semantics["schedule_fixtures"] == 72,
        "semantic checks incomplete",
    )
    for name, expected in semantics["source_sha256"].items():
        require(digest(ROOT / name) == expected, f"semantic input changed: {name}")
    tests = {}
    for name in (
        "tests",
        "spatial_pointwise-tests",
        "pointwise_blocking-tests",
        "b1-tests",
        "kernel_plan-tests",
        "xqmac8-tests",
        "weight_alignment-tests",
    ):
        path = ROOT / f"build/xqmac8/acc64-{name}.log"
        log = path.read_text()
        match = re.search(r"Ran (\d+) tests? in", log)
        require(
            match and re.search(r"^OK$", log, re.MULTILINE),
            f"failed regression: {name}",
        )
        tests[name] = {"tests": int(match[1]), "log_sha256": digest(path)}

    def metrics(summary):
        return {
            "instructions": int(summary["inference"]["instructions"]["value"]),
            "mix": {k: int(v["value"]) for k, v in summary["inference"]["mix"].items()},
            "footprint": {k: v["value"] for k, v in summary["footprint"].items()},
            "capture_id": summary["capture_id"],
            "elf_sha256": summary["elf_sha256"],
        }

    saved = int(before["inference"]["instructions"]["value"]) - int(
        after["inference"]["instructions"]["value"]
    )
    result = {
        "schema_version": 1,
        "status": "PASS",
        "configuration": "X1",
        "options": ["--xqmac8-weight-alignment 8", "--xqmac8-accumulator-bits 64"],
        "architectural_accumulator_bits": 32,
        "register_storage_bits": 64,
        "before": metrics(before),
        "after": metrics(after),
        "instructions_saved": saved,
        "instruction_reduction_percent": 100
        * saved
        / int(before["inference"]["instructions"]["value"]),
        "zero_immediate_addiw_retirements": {
            "before": zero_extensions(old),
            "after": zero_extensions(new),
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
            "raw_dot_controls_use_legacy_32_bit_wrapper": True,
        },
        "semantics": {
            "report_sha256": digest(semantics_path),
            "vectors": 10752,
            "chain_length": 64,
            "schedule_fixtures": 72,
            "native_asan_ubsan_and_both_spike_variants": "PASS",
        },
        "legacy_preservation": controls,
        "tests": tests,
        "gates": {
            name: "PASS"
            for name in (
                "wrapping_sign_extension_and_upper_bits",
                "all_reduction_schedules_and_odd_pixels",
                "tensor_suite",
                "two_rv64_inputs",
                "replay_all_cases",
                "repeat_profiles",
                "custom_counts",
                "memory_payloads_and_layouts",
                "nonpacked_nodes",
                "legacy_loadable_bytes",
                "regressions",
                "frozen_b0",
            )
        },
        "report_generator_sha256": digest(Path(__file__)),
        "limitations": [
            "Known zero-point Softmax domain outcome is preserved",
            "Spike retirements do not measure hardware cycles",
            "Raw evidence remains in ignored build/ and .deps/",
        ],
    }
    (ROOT / "results/profiling/X1-acc64/accumulator.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"Accumulator register gates: PASS; {saved:,} fewer instructions ({result['instruction_reduction_percent']:.2f}%)"
    )


if __name__ == "__main__":
    main()
