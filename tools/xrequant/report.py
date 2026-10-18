#!/usr/bin/env python3
"""Revalidate X2's numerical, ISA, compiler, profile and replay gates."""

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from compiler.build_evidence import artifact_path
from tools.build_a0 import verify_build
from tools.profile_compiler import verify_capture, make_summary
from tools.investigation.replay import verify_replay
from tools.freeze_compiler_baseline import verify_files
from tools.profile_spike import Elf
from tools.custom_isa import extension_identity
from tools.xqmac8.runtime import digest


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def capture(name):
    directory = (
        ROOT
        / "build/profiling/compiler"
        / read(ROOT / f"results/profiling/{name}/summary.json")["capture_id"]
    )
    verified = verify_capture(directory)
    return directory, verified, make_summary(directory, verified)


def artifact(directory, verified, name):
    return artifact_path(directory / "build_evidence/manifest.json", verified[1], name)


def main():
    verify_files(ROOT, read(ROOT / "tools/compiler/baseline.json")["frozen_files"])
    old_dir, old, before = capture("X1-tile2x4")
    new_dir, new, after = capture("X2")
    generated = ROOT / "build/compiler/X2"
    build = verify_build(generated, "rv64")
    require(
        build["binary_sha256"] == after["elf_sha256"], "profile/current binary mismatch"
    )
    a, b = [
        read(artifact(d, v, "memory_plan.json"))
        for d, v in ((old_dir, old), (new_dir, new))
    ]
    for key in ("tensors", "arena_bytes", "placements", "scratch", "aliases"):
        require(
            a[key] == b[key],
            f"physical workspace or original tensor layout changed: {key}",
        )
    require(
        artifact(old_dir, old, "prepared_ir.json").read_bytes()
        == artifact(new_dir, new, "prepared_ir.json").read_bytes(),
        "prepared constants changed",
    )
    total_req = sum(u.get("expected_xrequant_instructions", 0) for u in after["units"])
    total_mac = sum(u["expected_xqmac8_instructions"] for u in after["units"])
    require(total_req == 7369032 and total_mac == 42317184, "unexpected custom work")
    require(
        int(after["inference"]["mix"]["custom"]["value"]) == total_req + total_mac,
        "custom total mismatch",
    )
    regressions = []
    for a, b in zip(before["units"], after["units"]):
        require(a["id"] == b["id"], "unit identities changed")
        av, bv = [int(u["metrics"]["instructions"]["value"]) for u in (a, b)]
        if b.get("expected_xrequant_instructions", 0):
            if bv > av:
                regressions.append(
                    {
                        "node": b["nodes"][0],
                        "before": av,
                        "after": bv,
                        "additional_instructions": bv - av,
                    }
                )
        else:
            require(a["metrics"] == b["metrics"], f"untargeted node changed: {a['id']}")
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
            "incomplete tensor comparisons",
        )
        native[kind] = {
            "cases": 8,
            "node_arrays": proof["complete_node_arrays_compared"],
            "report_sha256": digest(path),
        }
    outputs = {}
    for case, path in (
        ("baseline", generated / "rv64/spike-verification.json"),
        ("random_42", ROOT / "build/xqmac8/X2/full-random_42/verification.json"),
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
        ROOT / "build/compiler/X2-replay/latest.json"
    )
    require(
        workload["configuration"] == "X2"
        and workload["nodes"] == [1, 4, 8, 10, 58, 61]
        and len(workload["cases"]) == 8
        and len(rows) == 52,
        "replay coverage incomplete",
    )
    require(
        set(manifest["kinds"]) == {"native", "sanitized", "rv64"},
        "replay backends incomplete",
    )
    require(
        read(replay / "build_evidence/manifest.json")["generation"]["artifacts"]
        == new[1]["generation"]["artifacts"],
        "replay/generation mismatch",
    )
    isa_path = ROOT / "build/xrequant/tests/verification.json"
    isa = read(isa_path)
    require(
        isa["status"] == "PASS"
        and isa["random_vectors"] == 10000
        and isa["profile_custom_retirements"] == isa["vectors"] + 64
        and isa["trap_fixtures"] == 18
        and isa["repeat_profiles_identical"],
        "ISA evidence incomplete",
    )
    require(
        digest(ROOT / "build/xrequant/tests/vectors.json") == isa["vectors_sha256"],
        "vectors changed",
    )
    for path, expected in isa["sources_sha256"].items():
        require(digest(ROOT / path) == expected, f"ISA source changed: {path}")
    for variant in ("ordinary", "profile"):
        require(
            isa["extensions"][variant] == extension_identity(variant, "X2"),
            "stale extension evidence",
        )
    controls = {}
    for cfg, reference, candidate in (
        ("B1", "B1-spatial2-oc2", "B1-x2-control"),
        ("X1", "X1-tile2x4", "X1-x2-control"),
    ):
        record = verify_build(ROOT / "build/compiler" / candidate, "rv64")
        paths = [
            ROOT / "build/compiler" / name / "rv64/a0.elf"
            for name in (reference, candidate)
        ]
        a, b = map(Elf, paths)
        require(
            a.allocated() == b.allocated() and a.loads == b.loads,
            f"legacy loadable bytes changed: {cfg}",
        )
        controls[cfg] = {
            "reference_elf_sha256": digest(paths[0]),
            "control_elf_sha256": digest(paths[1]),
            "allocated_sections_identical": True,
            "load_segments_identical": True,
        }
    tests = {}
    for name in ("compiler-tests", "all-compiler-tests", "profiler-tests"):
        path = ROOT / f"build/xqmac8/x2-{name}.log"
        log = path.read_text()
        counts = re.findall(r"Ran (\d+) tests? in", log)
        require(
            counts
            and re.search(r"^OK$", log, re.MULTILINE)
            and not re.search(r"^FAILED", log, re.MULTILINE),
            f"regression gate incomplete: {name}",
        )
        tests[name] = {"tests": int(counts[-1]), "log_sha256": digest(path)}

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
    result = {
        "schema_version": 1,
        "configuration": "X2",
        "status": "PASS",
        "stage": 8,
        "isa_contract": {
            "version": 1,
            "match": "0x0000100b",
            "mask": "0xfe00707f",
            "rv64_only": True,
            "accumulator_bits": 32,
            "double_rounding": True,
            "right_shift_range": [0, 31],
            "mode_bit": 62,
            "reserved_bit": 63,
            "output_addition": "wide_then_clip",
            "scale_only_writeback": "sign_extend_int32",
            "final_writeback": "sign_extend_int8",
            "old_rd_is_source": False,
        },
        "before": metrics(before),
        "after": metrics(after),
        "instructions_saved": saved,
        "instruction_reduction_percent": 100
        * saved
        / int(before["inference"]["instructions"]["value"]),
        "custom_counts": {"xqmac8": total_mac, "xrequant": total_req},
        "per_node_regressions": regressions,
        "native_differential": native,
        "rv64_outputs": outputs,
        "replay": {
            "artifact_id": replay.name,
            "fixtures": 52,
            "nodes": workload["nodes"],
            "input_cases": 8,
        },
        "isa_tests": {
            k: isa[k]
            for k in (
                "vectors",
                "random_vectors",
                "chain_length",
                "profile_custom_retirements",
                "trap_fixtures",
                "vectors_sha256",
                "elf_sha256",
            )
        },
        "isa_report_sha256": digest(isa_path),
        "legacy_preservation": controls,
        "tests": tests,
        "extensions": isa["extensions"],
        "gates": {
            name: "PASS"
            for name in (
                "independent_oracle_and_pinned_reference",
                "native_asan_ubsan",
                "both_spike_variants",
                "aliases_x0_sign_extension_rounding_and_traps",
                "isa_repeat_profiles",
                "eight_input_tensor_suite",
                "two_full_rv64_inputs",
                "six_operator_replay",
                "full_profile_repeat_identity",
                "per_opcode_counts",
                "prepared_ir_and_tensor_layouts_preserved",
                "legacy_loadable_bytes",
                "compiler_and_profiler_regressions",
                "frozen_b0",
            )
        },
        "hardware_gate": {
            "status": "BLOCKED",
            "reason": "CV-Wally Xrequant RTL, cycles, timing and area remain later work",
        },
        "source_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in sorted((ROOT / "tools/xrequant").glob("*.py"))
            + [
                ROOT / "tools/xrequant/extension.cc",
                ROOT / "kernels/xrequant/requant.h",
                ROOT / "compiler/xrequant.py",
                ROOT / "tests/compiler/test_xrequant.py",
            ]
        },
        "limitations": [
            "Two depthwise nodes regress; all per-node results retained",
            "Dynamic memory instructions increase 0.46%",
            "Known zero-point Softmax outcome is preserved",
            "Spike retirements are not hardware cycles",
            "Raw evidence remains in ignored build/ and .deps/",
        ],
    }
    output = ROOT / "results/xrequant"
    output.mkdir(parents=True, exist_ok=True)
    (output / "verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"X2 gates: PASS; {saved:,} fewer instructions ({result['instruction_reduction_percent']:.2f}%); hardware: BLOCKED pending RTL"
    )


if __name__ == "__main__":
    main()
