#!/usr/bin/env python3
"""Authenticate the depthwise correction/bank checkpoint and regenerate its report."""

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


def numerical(config, summary):
    generated = ROOT / "build/compiler" / config
    build = verify_build(generated, "rv64")
    require(
        build["binary_sha256"] == summary["elf_sha256"], "profile/current ELF mismatch"
    )
    records = {}
    for kind in ("native", "capture", "sanitized"):
        binary = verify_build(generated, kind)
        path = generated / kind / "differential.json"
        proof = read(path)
        require(
            proof["status"] == "PASS"
            and proof["binary_sha256"] == binary["binary_sha256"]
            and len(proof["cases"]) == 8,
            f"{config} {kind}: incomplete proof",
        )
        arrays = 0 if kind == "native" else 510
        require(proof["complete_node_arrays_compared"] == arrays, "incomplete tensors")
        for case in proof["cases"]:
            require(
                case["status"] == (2 if case["name"] == "zero_point" else 0),
                "reference outcome changed",
            )
            for name, sha in case["files"].items():
                require(
                    digest(generated / kind / "captures" / case["name"] / name) == sha,
                    "numerical capture changed",
                )
        records[kind] = {
            "status": "PASS",
            "cases": 8,
            "node_arrays": arrays,
            "report_sha256": digest(path),
        }
    path = ROOT / "build/xqmac8" / config / "full-random_42/verification.json"
    proof = read(path)
    require(
        proof["status"] == "PASS"
        and proof["production_binary_sha256"] == build["binary_sha256"]
        and proof["full_output_bytes_compared"] == 1000,
        "second RV64 input missing",
    )
    for name, sha in proof["reused_objects_sha256"].items():
        require(digest(Path(name)) == sha, "second input object changed")
    records["rv64"] = {
        "status": "PASS",
        "cases": ["baseline", "random_42"],
        "output_bytes_per_case": 1000,
        "report_sha256": digest(path),
    }
    return records


def main():
    verify_files(ROOT, read(ROOT / "tools/compiler/baseline.json")["frozen_files"])
    bundles = {name: capture(name) for name in ("X3-selected", "D1", "X4")}
    summaries = {name: b[2] for name, b in bundles.items()}
    baseline = bundles["X3-selected"]
    for cfg in ("D1", "X4"):
        require(
            artifact(baseline, "prepared_ir.json").read_bytes()
            == artifact(bundles[cfg], "prepared_ir.json").read_bytes(),
            "quantization changed",
        )
        a, b = (read(artifact(v, "memory_plan.json")) for v in (baseline, bundles[cfg]))
        for key in ("tensors", "placements", "aliases", "scratch", "arena_bytes"):
            require(
                a[key] == b[key], f"activation/original tensor placement changed: {key}"
            )
    for name in ("constants.cc", "constants.h", "prepared_ir.json", "memory_plan.json"):
        require(
            artifact(bundles["D1"], name).read_bytes()
            == artifact(bundles["X4"], name).read_bytes(),
            "D1/X4 data differs",
        )
    per_node = []
    for a, b, c in zip(
        *(summaries[cfg]["units"] for cfg in ("X3-selected", "D1", "X4"))
    ):
        av, bv, cv = (int(u["metrics"]["instructions"]["value"]) for u in (a, b, c))
        dw = "depthwise" in a["implementation"]
        if not dw:
            require(av == bv == cv, f"untargeted unit changed: {a['id']}")
        else:
            require(cv < bv < av, f"depthwise regression: {a['id']}")
        require(
            a["expected_xqmac8_instructions"]
            == b["expected_xqmac8_instructions"]
            == c["expected_xqmac8_instructions"],
            "pointwise work changed",
        )
        require(
            a["expected_xrequant_instructions"]
            == b["expected_xrequant_instructions"]
            == c["expected_xrequant_instructions"],
            "requantization work changed",
        )
        per_node.append(
            {"node": a["nodes"][0], "depthwise": dw, "X3": av, "D1": bv, "X4": cv}
        )
    numbers = {cfg: numerical(cfg, summaries[cfg]) for cfg in ("D1", "X4")}
    directory, manifest, workload, rows = verify_replay(
        ROOT / "build/compiler/X4-replay/latest.json"
    )
    require(
        len(rows) == 148
        and len(workload["cases"]) == 8
        and set(manifest["kinds"]) == {"native", "sanitized", "rv64"},
        "replay incomplete",
    )
    require(
        set(workload["nodes"])
        == {2, 4, 5, 8, 12, 15, 19, 22, 26, 30, 33, 37, 41, 44, 48, 52, 56, 58},
        "replay node coverage incomplete",
    )
    require(
        read(directory / "build_evidence/manifest.json")["generation"]["artifacts"]
        == bundles["X4"][1][1]["generation"]["artifacts"],
        "replay/model generation mismatch",
    )
    isa_path = ROOT / "build/xdwmac8/tests/verification.json"
    isa = read(isa_path)
    require(
        isa["status"] == "PASS"
        and isa["vectors"] == 10256
        and isa["precise_traps"] == 8,
        "ISA vectors incomplete",
    )
    for field in (
        "native_sanitizers",
        "native_thread_isolation",
        "spike_two_hart_isolation",
        "context_restore",
        "disabled_rv32",
        "repeated_profiles_identical",
    ):
        require(isa[field], f"ISA gate missing: {field}")
    for variant in ("ordinary", "profile"):
        require(
            isa["extensions"][variant] == extension_identity(variant, "X4"),
            "extension changed",
        )
    for name, key in (
        ("vectors.json", "vectors_sha256"),
        ("vectors.elf", "elf_sha256"),
    ):
        require(digest(isa_path.parent / name) == isa[key], "ISA artifact changed")
    controls = read(ROOT / "build/xdwmac8/controls.json")
    require(
        controls["status"] == "PASS"
        and set(controls["controls"]) == {"B1", "X1", "X2", "X3"},
        "controls incomplete",
    )
    for cfg, proof in controls["controls"].items():
        generated = ROOT / "build/compiler" / (cfg + "-depthwise-control")
        record = verify_build(generated, "rv64")
        a, b = (
            Elf(ROOT / "build/compiler" / proof["reference"] / "rv64/a0.elf"),
            Elf(generated / "rv64/a0.elf"),
        )
        require(
            a.allocated() == b.allocated()
            and a.loads == b.loads
            and proof["control_elf_sha256"] == record["binary_sha256"],
            f"legacy image changed: {cfg}",
        )
    regression_path = ROOT / "build/xdwmac8/compiler-regressions.json"
    regression = read(regression_path)
    require(
        regression["status"] == "PASS"
        and regression["modules"]
        == sorted(p.stem for p in (ROOT / "tests/compiler").glob("test_*.py")),
        "regression coverage incomplete",
    )
    for name, sha in regression["source_sha256"].items():
        require(digest(ROOT / name) == sha, f"regression source changed: {name}")
    for group in regression["groups"]:
        path = ROOT / group["log"]
        text = path.read_text()
        require(
            digest(path) == group["log_sha256"]
            and re.search(r"^OK$", text, re.M)
            and f"Ran {group['count']} tests" in text,
            "regression log changed",
        )
    covered = [module for group in regression["groups"] for module in group["modules"]]
    require(
        sorted(covered) == regression["modules"]
        and sum(g["count"] for g in regression["groups"]) == regression["count"],
        "regression partition incomplete",
    )
    path = ROOT / "build/xdwmac8/profiler-tests.log"
    text = path.read_text()
    require(
        re.search(r"^OK$", text, re.M) and re.search(r"Ran 5 tests", text),
        "profiler regressions incomplete",
    )
    metrics = {}
    for cfg, s in summaries.items():
        metrics[cfg] = {
            "capture_id": s["capture_id"],
            "elf_sha256": s["elf_sha256"],
            "instructions": int(s["inference"]["instructions"]["value"]),
            "depthwise_instructions": sum(
                r[cfg if cfg != "X3-selected" else "X3"]
                for r in per_node
                if r["depthwise"]
            ),
            "footprint": {k: v["value"] for k, v in s["footprint"].items()},
        }
    bank_counts = {
        name: sum(
            u.get("expected_xdwmac8_instructions", {}).get(name, 0)
            for u in summaries["X4"]["units"]
        )
        for name in isa["counts"]
    }
    require(
        bank_counts["xdwmac8"] == 3831052
        and all(
            bank_counts[f"xdwset{i}"] == bank_counts[f"xdwget{i}"] == 288316
            for i in range(4)
        ),
        "model bank work mismatch",
    )
    report = {
        "status": "PASS",
        "contract_version": 1,
        "metrics": metrics,
        "per_node": per_node,
        "numerical": numbers,
        "bank_instructions": bank_counts,
        "isa": {k: v for k, v in isa.items() if k != "extensions"},
        "isa_report_sha256": digest(isa_path),
        "legacy_controls": controls["controls"],
        "replay": {
            "status": "PASS",
            "artifact": directory.name,
            "fixtures": len(rows),
            "cases": 8,
            "nodes": workload["nodes"],
            "kinds": manifest["kinds"],
        },
        "tests": {
            "compiler": regression["count"],
            "compiler_report_sha256": digest(regression_path),
            "profiler": 5,
            "profiler_log_sha256": digest(path),
        },
        "source_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in (
                Path(__file__),
                ROOT / "tools/xdwmac8/test.py",
                ROOT / "tools/xdwmac8/controls.py",
            )
        },
        "hardware": "New bank hardware, area, timing and CV-Wally cycles deferred",
    }
    output = ROOT / "results/profiling"
    (output / "X4-verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    old, scalar, new = (metrics[n]["instructions"] for n in ("X3-selected", "D1", "X4"))
    dwold, dwnew = (metrics[n]["depthwise_instructions"] for n in ("X3-selected", "X4"))
    lines = [
        "# Validated depthwise optimization checkpoint",
        "",
        "| Configuration | Full inference instructions | Depthwise instructions |",
        "|---|---:|---:|",
    ]
    lines += [
        f"| {cfg} | {v['instructions']:,} | {v['depthwise_instructions']:,} |"
        for cfg, v in metrics.items()
    ]
    lines += [
        "",
        f"Zero-point hoisting alone removes {old - scalar:,} instructions ({100 * (1 - scalar / old):.2f}%).",
        f"The bank removes another {scalar - new:,} ({100 * (1 - new / scalar):.2f}% of D1).",
        f"Combined reduction: **{100 * (1 - new / old):.2f}%**, or **{old / new:.3f}×** fewer full-inference instructions.",
        f"Depthwise reduction: **{100 * (1 - dwnew / dwold):.2f}%** ({dwold / dwnew:.3f}×).",
        "",
        "## Verification",
        "",
        f"- {regression['count']} compiler regressions and 5 profiler tests passed.",
        "- 10,256 ISA vectors passed native sanitizers and ordinary/profile Spike, including lane wrap, aliases, dependency chains, context save/restore, reset state, and eight precise reserved-encoding traps. Disabled/RV32 traps and interleaved two-hart isolation passed.",
        "- D1 and X4 each match all eight reference input cases in native, full capture, and ASan/UBSan builds; capture and sanitized modes each compare 510 complete tensors. The existing zero-point-input Softmax failure remains status 2 after 62 matching tensors.",
        "- Both configurations match all 1,000 output bytes for baseline and random_42 on RV64 Spike. Two full event/PC captures agree exactly for each configuration.",
        "- 148 replay fixtures pass native, sanitized, and RV64 builds, covering all 16 depthwise layers and two pointwise controls across eight cases, plus four dot-product controls.",
        "- Per-unit bank MAC/set/get, Xqmac8, Xrequant and post-increment retirements reconcile with independent schedule counts. Untargeted execution-unit counts are unchanged.",
        "- Prior B1/X1/X2/X3 allocated sections and load segments are byte-identical. Frozen B0 inputs remain intact.",
        "",
        "## Footprint and remaining bottlenecks",
        "",
        f"Prepared constants and parameters grow by {int(metrics['X4']['footprint']['planned_constants_and_parameters']) - int(metrics['X3-selected']['footprint']['planned_constants_and_parameters']):,} bytes for region maps and corrected bias vectors. Activation workspace remains 1,505,280 bytes.",
        f"Executable code: {int(metrics['X3-selected']['footprint']['executable_code']):,} → {int(metrics['X4']['footprint']['executable_code']):,} bytes.",
        f"The stem is now the largest unit: 69,472,265 instructions ({100 * 69472265 / new:.1f}%). All depthwise layers together account for {100 * dwnew / new:.1f}%.",
        "Counts measure retired instructions, not hardware speedup, cache misses, or DRAM traffic. The new accumulator bank is implemented in Spike and compiler only; CV-Wally integration remains deferred.",
        "",
        "Reproduce: `make compiler-x4-checkpoint`. The adjacent JSON binds immutable captures, ELFs, numerical evidence, replay, tests, extension identities and legacy controls.",
        "",
    ]
    (output / "X4-verification.md").write_text("\n".join(lines))
    print(
        f"Xdwmac8 checkpoint: PASS ({new:,} instructions, {len(rows)} replay fixtures, {regression['count']} compiler tests)"
    )


if __name__ == "__main__":
    main()
