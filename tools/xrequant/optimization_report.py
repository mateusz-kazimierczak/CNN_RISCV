#!/usr/bin/env python3
"""Verify production X2 scheduling policies against the retained X2 reference."""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from compiler.build_evidence import artifact_path, digest
from compiler.kernel_plan import KernelPlan
from compiler.quantization import PreparedGraph
from compiler.xrequant import (
    ADD64_CHOICE,
    OUTLINE_CHOICE,
    add_int32_bounds,
    optimization_options,
)
from tools.build_a0 import verify_build
from tools.custom_isa import extension_identity
from tools.freeze_compiler_baseline import verify_files
from tools.investigation.replay import verify_replay
from tools.profile_spike import Elf
from tools.xrequant.report import capture, read, require


def artifact(bundle, name):
    directory, verified, _ = bundle
    return artifact_path(directory / "build_evidence/manifest.json", verified[1], name)


def metrics(summary):
    return {
        "capture_id": summary["capture_id"],
        "elf_sha256": summary["elf_sha256"],
        "instructions": int(summary["inference"]["instructions"]["value"]),
        "mix": {k: int(v["value"]) for k, v in summary["inference"]["mix"].items()},
        "footprint": {k: v["value"] for k, v in summary["footprint"].items()},
    }


def main():
    verify_files(ROOT, read(ROOT / "tools/compiler/baseline.json")["frozen_files"])
    before = capture("X2")
    after = capture("X2-optimized")
    generated = ROOT / "build/compiler/X2-optimized"
    build = verify_build(generated, "rv64")
    require(
        build["binary_sha256"] == after[2]["elf_sha256"], "current ELF/profile mismatch"
    )
    require("ELF audit: PASS" in build["isa_audit"], "ISA audit incomplete")
    for name in ("constants.cc", "constants.h", "prepared_ir.json", "memory_plan.json"):
        require(
            artifact(before, name).read_bytes() == artifact(after, name).read_bytes(),
            f"data or physical layout changed: {name}",
        )
    prepared = PreparedGraph.from_json(
        artifact(after, "prepared_ir.json").read_text(), after[1][2]
    )
    plan = KernelPlan.from_json(
        artifact(after, "kernel_plan.json").read_text(), after[1][2], prepared
    )
    require(
        optimization_options(plan.nodes)
        == {
            "xrequant_depthwise_outlining": "selected",
            "xrequant_add_register_bits": 64,
        },
        "production policies incomplete",
    )
    outlined = [n.node for n in plan.nodes if OUTLINE_CHOICE in n.choices]
    wide = [n.node for n in plan.nodes if ADD64_CHOICE in n.choices]
    require(
        outlined == [2, 8, 22, 26, 33, 37, 41, 56]
        and wide == [10, 17, 24, 28, 35, 39, 46, 50, 54],
        "optimization scope changed",
    )
    per_node = []
    for a, b in zip(before[2]["units"], after[2]["units"]):
        require(a["id"] == b["id"], "execution-unit inventory changed")
        av, bv = (int(u["metrics"]["instructions"]["value"]) for u in (a, b))
        node = b["nodes"][0]
        require(
            bv < av if node in outlined + wide else bv == av,
            f"unexpected node retirement change: {node}",
        )
        if bv != av:
            per_node.append({"node": node, "before": av, "after": bv, "saved": av - bv})
    custom = []
    for bundle in (before, after):
        v = bundle[1]
        counts = Counter()
        for pc, n in v[6]["histogram"].items():
            mnemonic = v[4][pc]["mnemonic"]
            if mnemonic in ("xqmac8", "xrequant"):
                counts[mnemonic] += n
        custom.append(dict(counts))
    require(
        custom[0] == custom[1] == {"xqmac8": 42317184, "xrequant": 7369032},
        "custom work changed",
    )
    prototype = read(ROOT / "results/xrequant/optimization-investigation.json")[
        "experiments"
    ]["combined"]
    require(
        int(after[2]["inference"]["instructions"]["value"])
        == prototype["instructions"],
        "production retirements differ from measured prototype",
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
            f"incomplete numerical proof: {kind}",
        )
        require(
            proof["complete_node_arrays_compared"] == (0 if kind == "native" else 510),
            "incomplete full tensor comparisons",
        )
        for case in proof["cases"]:
            require(
                case["status"] == (2 if case["name"] == "zero_point" else 0),
                "input outcome changed",
            )
            for name, expected in case["files"].items():
                require(
                    digest(generated / kind / "captures" / case["name"] / name)
                    == expected,
                    "differential artifact changed",
                )
        numerical[kind] = {
            "status": "PASS",
            "cases": 8,
            "node_arrays": proof["complete_node_arrays_compared"],
            "report_sha256": digest(path),
        }
    path = ROOT / "build/xqmac8/X2-optimized/full-random_42/verification.json"
    proof = read(path)
    require(
        proof["production_binary_sha256"] == build["binary_sha256"]
        and proof["full_output_bytes_compared"] == 1000
        and proof["status"] == "PASS",
        "random_42 RV64 proof mismatch",
    )
    numerical["rv64"] = {
        "status": "PASS",
        "cases": ["baseline", "random_42"],
        "bytes_per_output": 1000,
        "random_42_report_sha256": digest(path),
    }

    replay, manifest, workload, rows = verify_replay(
        ROOT / "build/compiler/X2-optimized-replay/latest.json"
    )
    require(
        workload["nodes"] == [2, 4, 8, 10, 22, 26, 33, 37, 41, 56, 58]
        and len(workload["cases"]) == 8
        and len(rows) == 92,
        "replay coverage incomplete",
    )
    require(
        set(manifest["kinds"]) == {"native", "sanitized", "rv64"},
        "replay backends incomplete",
    )
    require(
        read(replay / "build_evidence/manifest.json")["generation"]["artifacts"]
        == after[1][1]["generation"]["artifacts"],
        "replay/generation mismatch",
    )
    for kind in manifest["kinds"]:
        record = read(replay / kind / "build.json")
        for name in (
            "kernels/rv64imc/depthwise.h",
            "kernels/project/operators.h",
            "kernels/xrequant/add64.h",
        ):
            matches = [
                v
                for k, v in record["dependency_sha256"].items()
                if k.endswith("/" + name)
            ]
            require(
                matches == [digest(ROOT / name)],
                f"replay used different production source: {kind}/{name}",
            )

    controls = {}
    for cfg, reference, candidate in (
        ("B1", "B1-spatial2-oc2", "B1-x2-control"),
        ("X1", "X1-tile2x4", "X1-x2-control"),
        ("X2", "X2", "X2-optimization-control"),
    ):
        control = verify_build(ROOT / "build/compiler" / candidate, "rv64")
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
            "status": "PASS",
            "allocated_sections_identical": True,
            "load_segments_identical": True,
            "reference_elf_sha256": digest(paths[0]),
            "control_elf_sha256": control["binary_sha256"],
            "isa_audit": control["isa_audit"],
        }
    tests = {}
    for name, path in (
        ("policies", ROOT / "build/xrequant/optimized-policy-tests.log"),
        ("compiler", ROOT / "build/xqmac8/x2-all-compiler-tests.log"),
        ("profiler", ROOT / "build/xqmac8/x2-profiler-tests.log"),
    ):
        log = path.read_text()
        counts = re.findall(r"Ran (\d+) tests? in", log)
        require(
            counts
            and re.search(r"^OK$", log, re.MULTILINE)
            and not re.search(r"^FAILED", log, re.MULTILINE),
            f"regression gate incomplete: {name}",
        )
        tests[name] = {
            "status": "PASS",
            "tests": int(counts[-1]),
            "log_sha256": digest(path),
        }
    isa_path = ROOT / "build/xrequant/tests/verification.json"
    isa = read(isa_path)
    require(
        isa["status"] == "PASS" and isa["random_vectors"] == 10000,
        "ISA proof incomplete",
    )
    for name, expected in isa["sources_sha256"].items():
        require(digest(ROOT / name) == expected, f"ISA source changed: {name}")
    for variant in ("ordinary", "profile"):
        require(
            isa["extensions"][variant] == extension_identity(variant, "X2"),
            "extension identity changed",
        )
    a, b = metrics(before[2]), metrics(after[2])
    saved = a["instructions"] - b["instructions"]
    result = {
        "schema_version": 1,
        "configuration": "X2",
        "checkpoint": "X2-optimized",
        "status": "PASS",
        "policies": optimization_options(plan.nodes),
        "outlined_nodes": outlined,
        "wide_add_nodes": wide,
        "add_sum_int32_bounds": {
            str(n): add_int32_bounds(prepared.nodes[n].integers) for n in wide
        },
        "before": a,
        "after": b,
        "instructions_saved": saved,
        "instruction_reduction_percent": 100 * saved / a["instructions"],
        "custom_counts": custom[1],
        "changed_nodes": per_node,
        "per_node_regressions": [],
        "numerical_validation": numerical,
        "legacy_preservation": controls,
        "tests": tests,
        "replay": {
            "status": "PASS",
            "artifact_id": replay.name,
            "fixtures": len(rows),
            "nodes": workload["nodes"],
            "cases": 8,
            "kinds": manifest["kinds"],
        },
        "isa_proof": {
            "status": "PASS",
            "reused_unchanged_contract": True,
            "vectors": isa["vectors"],
            "random_vectors": isa["random_vectors"],
            "report_sha256": digest(isa_path),
        },
        "gates": {
            "compiler_policies": "PASS",
            "numerical": "PASS",
            "rv64_outputs": "PASS",
            "repeat_profiles": "PASS",
            "kernel_replay": "PASS",
            "legacy_controls": "PASS",
            "regressions": "PASS",
            "hardware_cycles_timing_area": "BLOCKED: pending CV-Wally RTL",
        },
    }
    output = ROOT / "results/xrequant/optimization-verification.json"
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(
        f"X2 optimized: PASS; {saved:,} fewer instructions ({result['instruction_reduction_percent']:.2f}%). {output}"
    )


if __name__ == "__main__":
    main()
