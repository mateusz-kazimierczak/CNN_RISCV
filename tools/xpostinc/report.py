#!/usr/bin/env python3
"""Authenticate X3 profiles, correctness gates, replay and unchanged legacy images."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from compiler.build_evidence import artifact_path, digest
from tools.build_a0 import verify_build
from tools.custom_isa import extension_identity
from tools.freeze_compiler_baseline import verify_files
from tools.investigation.replay import verify_replay
from tools.profile_spike import Elf
from tools.xrequant.report import capture, read, require


def artifact(bundle, name):
    directory, verified, _ = bundle
    return artifact_path(directory / "build_evidence/manifest.json", verified[1], name)


def main():
    verify_files(ROOT, read(ROOT / "tools/compiler/baseline.json")["frozen_files"])
    before, broad, after = (
        capture(name) for name in ("X2-optimized", "X3", "X3-selected")
    )
    generated = ROOT / "build/compiler/X3-selected"
    build = verify_build(generated, "rv64")
    require(
        build["binary_sha256"] == after[2]["elf_sha256"],
        "production/profile ELF differs",
    )
    for experiment in (broad, after):
        for name in (
            "constants.cc",
            "constants.h",
            "prepared_ir.json",
            "memory_plan.json",
        ):
            require(
                artifact(before, name).read_bytes()
                == artifact(experiment, name).read_bytes(),
                f"data changed: {name}",
            )
        for old, new in zip(before[2]["units"], experiment[2]["units"]):
            require(
                old["expected_xqmac8_instructions"]
                == new["expected_xqmac8_instructions"],
                "MAC schedule changed",
            )
            require(
                old["expected_xrequant_instructions"]
                == new["expected_xrequant_instructions"],
                "requant schedule changed",
            )
    per_node = []
    for old, new in zip(before[2]["units"], after[2]["units"]):
        a, b = (int(u["metrics"]["instructions"]["value"]) for u in (old, new))
        require(b <= a, f"selected policy regresses node {new['nodes']}")
        if a != b:
            per_node.append(
                {"node": new["nodes"][0], "before": a, "after": b, "saved": a - b}
            )
    numerical = {}
    for kind in ("native", "capture", "sanitized"):
        record = verify_build(generated, kind)
        path = generated / kind / "differential.json"
        proof = read(path)
        require(
            proof["status"] == "PASS"
            and proof["binary_sha256"] == record["binary_sha256"]
            and len(proof["cases"]) == 8,
            f"missing numerical proof: {kind}",
        )
        require(
            proof["complete_node_arrays_compared"] == (0 if kind == "native" else 510),
            "incomplete tensor comparisons",
        )
        for case in proof["cases"]:
            require(
                case["status"] == (2 if case["name"] == "zero_point" else 0),
                "reference outcome changed",
            )
            for name, expected in case["files"].items():
                require(
                    digest(generated / kind / "captures" / case["name"] / name)
                    == expected,
                    "numerical artifact changed",
                )
        numerical[kind] = {
            "status": "PASS",
            "cases": 8,
            "node_arrays": proof["complete_node_arrays_compared"],
            "report_sha256": digest(path),
        }
    path = ROOT / "build/xqmac8/X3-selected/full-random_42/verification.json"
    random = read(path)
    require(
        random["status"] == "PASS"
        and random["production_binary_sha256"] == build["binary_sha256"]
        and random["full_output_bytes_compared"] == 1000,
        "second RV64 input mismatch",
    )
    numerical["rv64"] = {
        "status": "PASS",
        "cases": ["baseline", "random_42"],
        "bytes_per_output": 1000,
        "second_input_report_sha256": digest(path),
    }
    replay, manifest, workload, rows = verify_replay(
        ROOT / "build/compiler/X3-selected-replay/latest.json"
    )
    require(
        len(workload["cases"]) == 8
        and len(rows) == 100
        and set(manifest["kinds"]) == {"native", "sanitized", "rv64"},
        "incomplete replay",
    )
    require(
        read(replay / "build_evidence/manifest.json")["generation"]["artifacts"]
        == after[1][1]["generation"]["artifacts"],
        "replay/model generation differs",
    )
    isa_path = ROOT / "build/xpostinc/tests/verification.json"
    isa = read(isa_path)
    require(
        isa["status"] == "PASS"
        and isa["vectors"] == 12672
        and isa["precise_fault_cases"] == 35
        and isa["native"]["status"] == "PASS",
        "incomplete ISA proof",
    )
    require(
        isa["vectors_sha256"] == digest(isa_path.parent / "vectors.json")
        and isa["elf_sha256"] == digest(isa_path.parent / "vectors.elf"),
        "ISA artifacts changed",
    )
    for variant in ("ordinary", "profile"):
        require(
            isa["extensions"][variant] == extension_identity(variant, "X3"),
            "ISA extension identity changed",
        )
    micro_path = ROOT / "build/xpostinc/microbenchmark/verification.json"
    micro = read(micro_path)
    require(
        micro["status"] == "PASS"
        and micro["counts"] == {"baseline": 6150, "postinc": 4102},
        "microbenchmark incomplete",
    )
    require(
        micro["elf_sha256"] == digest(micro_path.parent / "copy.elf")
        and micro["extensions"] == extension_identity("profile", "X3"),
        "microbenchmark identity changed",
    )
    controls = {}
    for cfg, reference in (
        ("B1", "B1-spatial2-oc2"),
        ("X1", "X1-tile2x4"),
        ("X2", "X2-optimized"),
    ):
        directory = ROOT / "build/compiler" / (cfg + "-postinc-control")
        record = verify_build(directory, "rv64")
        a, b = (
            Elf(ROOT / "build/compiler" / reference / "rv64/a0.elf"),
            Elf(directory / "rv64/a0.elf"),
        )
        require(
            a.allocated() == b.allocated() and a.loads == b.loads,
            f"legacy image changed: {cfg}",
        )
        controls[cfg] = {
            "status": "PASS",
            "allocated_sections_identical": True,
            "load_segments_identical": True,
            "control_elf_sha256": record["binary_sha256"],
        }
    regression_path = ROOT / "build/xpostinc/compiler-regressions.json"
    regression = read(regression_path)
    require(regression["status"] == "PASS", "compiler regressions incomplete")
    require(
        regression["modules"]
        == sorted(p.stem for p in (ROOT / "tests/compiler").glob("test_*.py")),
        "compiler regression module coverage incomplete",
    )
    covered = []
    for group in regression["groups"]:
        path = ROOT / group["log"]
        text = path.read_text()
        match = re.search(r"Ran (\d+) tests? in", text)
        require(
            digest(path) == group["log_sha256"]
            and match
            and int(match[1]) == group["count"]
            and re.search(r"^OK$", text, re.MULTILINE),
            "compiler regression log changed",
        )
        covered.extend(group["modules"])
    require(
        sorted(covered) == regression["modules"]
        and sum(g["count"] for g in regression["groups"]) == regression["count"],
        "compiler regression partition incomplete",
    )
    for name, expected in regression["source_sha256"].items():
        require(
            digest(ROOT / name) == expected,
            f"compiler regression source changed: {name}",
        )
    tests = {
        "compiler": {
            "status": "PASS",
            "count": regression["count"],
            "report_sha256": digest(regression_path),
        }
    }
    for label, name in (("profiler", "profiler-tests.log"),):
        path = ROOT / "build/xpostinc" / name
        text = path.read_text()
        match = re.search(r"Ran (\d+) tests? in", text)
        require(
            match and re.search(r"^OK$", text, re.MULTILINE) and "FAILED" not in text,
            f"tests incomplete: {name}",
        )
        tests[label] = {
            "status": "PASS",
            "count": int(match[1]),
            "log_sha256": digest(path),
        }
    metrics = {}
    for name, bundle in (
        ("X2-optimized", before),
        ("X3-all", broad),
        ("X3-selected", after),
    ):
        summary = bundle[2]
        metrics[name] = {
            "capture_id": summary["capture_id"],
            "elf_sha256": summary["elf_sha256"],
            "instructions": int(summary["inference"]["instructions"]["value"]),
            "mix": {k: int(v["value"]) for k, v in summary["inference"]["mix"].items()},
            "postincrement": {
                k: int(v["value"])
                for k, v in summary["inference"].get("postincrement", {}).items()
            },
            "executable_bytes": int(summary["footprint"]["executable_code"]["value"]),
        }
    report = {
        "status": "PASS",
        "contract_version": 1,
        "metrics": metrics,
        "per_node": per_node,
        "numerical": numerical,
        "isa": {
            "status": "PASS",
            "vectors": isa["vectors"],
            "precise_fault_cases": isa["precise_fault_cases"],
            "native": isa["native"],
            "report_sha256": digest(isa_path),
        },
        "microbenchmark": {k: v for k, v in micro.items() if k != "extensions"},
        "replay": {
            "status": "PASS",
            "artifact": replay.name,
            "nodes": workload["nodes"],
            "fixtures": len(rows),
            "cases": 8,
            "builds": manifest["kinds"],
        },
        "legacy_controls": controls,
        "tests": tests,
        "source_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in (
                Path(__file__),
                ROOT / "tools/xpostinc/test.py",
                ROOT / "tools/xpostinc/microbenchmark.py",
                ROOT / "tests/compiler/test_xpostinc.py",
            )
        },
        "hardware": "CV-Wally cycles, timing and area not implemented or measured by this checkpoint",
    }
    output = ROOT / "results/xpostinc"
    output.mkdir(parents=True, exist_ok=True)
    (output / "verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"Xpostinc checkpoint: PASS ({metrics['X3-selected']['instructions']:,} instructions, {len(rows)} replay fixtures)"
    )


if __name__ == "__main__":
    main()
