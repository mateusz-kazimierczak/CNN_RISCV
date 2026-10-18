#!/usr/bin/env python3
"""Publish compact Stage 7 gates only after verifying the saved execution evidence."""

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from tools.build_a0 import verify_build
from tools.profile_compiler import make_summary, verify_capture
from tools.profile_spike import Elf
from tools.investigation.replay import verify_replay
from tools.xqmac8.runtime import digest, extension_identity
from tools.freeze_compiler_baseline import verify_files


def read(path):
    return json.loads(Path(path).read_text())


def main():
    contract = ROOT / "tools/compiler/baseline.json"
    verify_files(ROOT, read(contract)["frozen_files"])
    generated = ROOT / "build/compiler/X1"
    build = verify_build(generated, "rv64")
    summary = read(ROOT / "results/profiling/X1/summary.json")
    capture = ROOT / "build/profiling/compiler" / summary["capture_id"]
    verified = verify_capture(capture)
    measured = make_summary(capture, verified)
    if measured["elf_sha256"] != build["binary_sha256"]:
        raise ValueError("profile does not belong to the current X1 ELF")
    replay, _, workload, rows = verify_replay(
        ROOT / "build/compiler/X1-replay/latest.json"
    )
    if (
        workload["configuration"] != "X1"
        or workload["nodes"] != [4, 58]
        or len(workload["cases"]) != 8
        or len(rows) != 20
    ):
        raise ValueError("X1 replay coverage incomplete")
    isa = read(ROOT / "build/xqmac8/tests/verification.json")
    if (
        isa["status"] != "PASS"
        or isa["random_vectors"] != 10000
        or not isa["repeat_profiles_identical"]
    ):
        raise ValueError("ISA tests incomplete")
    for variant in ("ordinary", "profile"):
        if isa["extensions"][variant] != extension_identity(variant):
            raise ValueError("ISA tests use an outdated Spike extension")
    baseline = read(generated / "rv64/spike-verification.json")
    second = read(ROOT / "build/xqmac8/full-random_42/verification.json")
    if (
        baseline["binary_sha256"] != build["binary_sha256"]
        or second["production_binary_sha256"] != build["binary_sha256"]
    ):
        raise ValueError("full-input checks do not belong to the current X1 ELF")
    native = {}
    for kind in ("native", "capture", "sanitized"):
        record = verify_build(generated, kind)
        diff = read(generated / kind / "differential.json")
        if (
            diff["configuration"] != "X1"
            or len(diff["cases"]) != 8
            or diff["binary_sha256"] != record["binary_sha256"]
        ):
            raise ValueError("native differential evidence incomplete")
        native[kind] = {
            "cases": 8,
            "node_arrays": diff["complete_node_arrays_compared"],
            "report_sha256": digest(generated / kind / "differential.json"),
            "binary_sha256": record["binary_sha256"],
        }
    if any(native[k]["node_arrays"] != 510 for k in ("capture", "sanitized")):
        raise ValueError("not all reference node tensors were compared")
    old_path = ROOT / "build/compiler/B1-spatial2-oc2/rv64/a0.elf"
    control_path = ROOT / "build/compiler/B1-x1-control/rv64/a0.elf"
    old, control = Elf(old_path), Elf(control_path)
    if old.allocated() != control.allocated() or old.loads != control.loads:
        raise ValueError("accepted B1 changed")
    tests = {}
    for name in ("compiler-regressions", "profiler-regressions", "compiler-tests"):
        path = ROOT / f"build/xqmac8/{name}.log"
        log = path.read_text()
        count = re.search(r"Ran (\d+) tests? in", log)
        if not count or not re.search(r"^OK(?: \(.*\))?$", log, re.MULTILINE):
            raise ValueError(f"regression tests have not passed: {name}")
        tests[name] = {"tests": int(count[1]), "log_sha256": digest(path)}
    result = {
        "schema_version": 1,
        "configuration": "X1",
        "status": "PASS",
        "stage": 7,
        "isa_contract": {
            "version": 1,
            "match": "0x0000000b",
            "mask": "0xfe00707f",
            "accumulator_bits": 32,
            "old_rd_is_source": True,
            "writeback": "sign_extend_64",
            "overflow": "wrap_modulo_2^32",
        },
        "gates": {
            name: "PASS"
            for name in (
                "directed_and_random_isa",
                "native_asan_ubsan",
                "spike_decode_disassembly_and_traps",
                "isa_fixture_repeat_counts",
                "native_full_tensor_suite",
                "rv64_two_full_inputs",
                "node_replay_all_inputs_and_microbenchmarks",
                "full_profile_repeat_identity",
                "custom_counts_match_eight_product_groups",
                "b1_loadable_bytes_preserved",
                "b0_frozen_artifacts_and_tools",
                "compiler_and_profiler_regressions",
            )
        },
        "isa_tests": {
            k: isa[k]
            for k in (
                "vectors",
                "random_vectors",
                "profile_custom_retirements",
                "vectors_sha256",
                "elf_sha256",
            )
        },
        "native_differential": native,
        "tests": tests,
        "rv64_output_cases": {
            "baseline": {
                "bytes_compared": baseline["full_output_bytes_compared"],
                "verification_sha256": digest(
                    generated / "rv64/spike-verification.json"
                ),
            },
            "random_42": {
                "bytes_compared": second["full_output_bytes_compared"],
                "verification_sha256": digest(
                    ROOT / "build/xqmac8/full-random_42/verification.json"
                ),
            },
        },
        "profile": {
            "capture_id": capture.name,
            "elf_sha256": build["binary_sha256"],
            "instructions": measured["inference"]["instructions"]["value"],
            "custom_instructions": measured["inference"]["mix"]["custom"]["value"],
            "parent": measured["comparisons"][-1]["reference"],
        },
        "replay": {
            "artifact_id": replay.name,
            "fixtures": len(rows),
            "nodes": [4, 58],
            "input_cases": 8,
            "microbenchmarks": [
                {
                    "fixture": r["fixture"],
                    "instructions": r["unit"]["instructions"]["value"],
                    "custom_instructions": r["unit"]["mix"]["custom"]["value"],
                }
                for r in rows
                if r["kind"] == "microbenchmark"
            ],
        },
        "b1_preservation": {
            "baseline_elf_sha256": digest(old_path),
            "control_elf_sha256": digest(control_path),
            "allocated_sections_identical": True,
            "load_segments_identical": True,
        },
        "b0_frozen_contract_sha256": digest(contract),
        "extension_libraries": {
            v: {
                "library_sha256": extension_identity(v)["library_sha256"],
                "build_manifest_sha256": digest(ROOT / f"build/xqmac8/{v}/build.json"),
            }
            for v in ("ordinary", "profile")
        },
        "source_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in sorted((ROOT / "tools/xqmac8").glob("*.py"))
            + [
                ROOT / "tools/xqmac8/extension.cc",
                ROOT / "kernels/xqmac8/dot8.h",
                ROOT / "tests/compiler/test_xqmac8.py",
                ROOT / "tools/audit_isa_elf.py",
            ]
        },
        "deferred_hardware_gate": {
            "status": "BLOCKED",
            "reason": "CV-Wally Xqmac8 implementation, cycles, timing and area are the next workstream",
        },
        "limitations": [
            "Known zero-point Softmax domain failure is preserved",
            "Spike retirements are not hardware cycles",
            "Raw evidence is in ignored build/ and .deps/ directories",
        ],
    }
    output = ROOT / "results/xqmac8"
    output.mkdir(parents=True, exist_ok=True)
    (output / "verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print("X1 Stage 7 functional, profiling and regression gates: PASS")


if __name__ == "__main__":
    main()
