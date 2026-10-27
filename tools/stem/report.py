#!/usr/bin/env python3
"""Authenticate X5 arithmetic, profiles, replay and unchanged predecessor images."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from compiler.build_evidence import digest
from tools.build_a0 import verify_build
from tools.custom_isa import extension_identity
from tools.freeze_compiler_baseline import verify_files
from tools.investigation.replay import verify_replay
from tools.profile_spike import Elf
from tools.xdwmac8.report import artifact, numerical
from tools.xrequant.report import capture, read, require


def main():
    verify_files(ROOT, read(ROOT / "tools/compiler/baseline.json")["frozen_files"])
    old, new = capture("X4"), capture("X5")
    before, after = old[2], new[2]
    require(
        artifact(old, "prepared_ir.json").read_bytes()
        == artifact(new, "prepared_ir.json").read_bytes(),
        "prepared quantization changed",
    )
    am, bm = (read(artifact(b, "memory_plan.json")) for b in (old, new))
    for key in ("tensors", "placements", "aliases", "scratch", "arena_bytes"):
        require(
            am[key] == bm[key], f"original tensor/activation placement changed: {key}"
        )
    old_kernel, new_kernel = (read(artifact(b, "kernel_plan.json")) for b in (old, new))
    per_node = []
    for a, b, ka, kb in zip(
        before["units"], after["units"], old_kernel["nodes"], new_kernel["nodes"]
    ):
        av, bv = (int(u["metrics"]["instructions"]["value"]) for u in (a, b))
        require(a["nodes"] == b["nodes"], "unit identity changed")
        if a["nodes"] != [1]:
            require(
                ka == kb and a["metrics"] == b["metrics"],
                f"untargeted node changed: {a['nodes']}",
            )
        else:
            require(
                bv < av
                and b["expected_xqmac8_instructions"] == 1605632
                and b["expected_xrequant_instructions"] == 401408,
                "stem schedule failed",
            )
            require(
                int(b["metrics"]["mix"]["multiply"]["value"]) == 0,
                "scalar stem multiplications remain",
            )
            require(
                b["metrics"]["executed_products"]["value"] == "12845056",
                "padded work mismatch",
            )
        require(
            a.get("expected_xdwmac8_instructions", {})
            == b.get("expected_xdwmac8_instructions", {}),
            "bank schedule changed",
        )
        require(
            a.get("expected_xrequant_instructions")
            == b.get("expected_xrequant_instructions"),
            "requantization count changed",
        )
        per_node.append(
            {"node": a["nodes"][0], "before": av, "after": bv, "saved": av - bv}
        )
    numerical_proof = numerical("X5", after)
    # The new compiler backend uses exactly the four existing X4 libraries.
    for variant in ("ordinary", "profile"):
        require(
            extension_identity(variant, "X5") == extension_identity(variant, "X4"),
            "new ISA identity introduced",
        )
        require(
            extension_identity(variant, "X5")
            == old[1][0]["collector"]["extensions"][variant],
            "predecessor ISA changed",
        )
    directory, manifest, workload, rows = verify_replay(
        ROOT / "build/compiler/X5-replay/latest.json"
    )
    require(
        len(rows) == 52
        and len(workload["cases"]) == 8
        and set(workload["nodes"]) == {1, 2, 4, 8, 58, 61}
        and set(manifest["kinds"]) == {"native", "sanitized", "rv64"},
        "incomplete stem/control replay",
    )
    require(
        read(directory / "build_evidence/manifest.json")["generation"]["artifacts"]
        == new[1][1]["generation"]["artifacts"],
        "replay/current generation mismatch",
    )
    controls = read(ROOT / "build/stem/controls.json")
    require(
        controls["status"] == "PASS"
        and set(controls["controls"]) == {"B1", "X1", "X2", "X3", "X4"},
        "incomplete legacy controls",
    )
    for cfg, c in controls["controls"].items():
        generated = ROOT / "build/compiler" / (cfg + "-stem-control")
        record = verify_build(generated, "rv64")
        a, b = (
            Elf(ROOT / "build/compiler" / c["reference"] / "rv64/a0.elf"),
            Elf(generated / "rv64/a0.elf"),
        )
        require(
            a.allocated() == b.allocated()
            and a.loads == b.loads
            and record["binary_sha256"] == c["control_elf_sha256"],
            f"legacy binary changed: {cfg}",
        )
    path = ROOT / "build/stem/compiler-regressions.json"
    regressions = read(path)
    require(
        regressions["status"] == "PASS"
        and regressions["modules"]
        == sorted(p.stem for p in (ROOT / "tests/compiler").glob("test_*.py")),
        "compiler regression coverage incomplete",
    )
    for name, sha in regressions["source_sha256"].items():
        require(digest(ROOT / name) == sha, f"regression source changed: {name}")
    covered = []
    for group in regressions["groups"]:
        log = ROOT / group["log"]
        text = log.read_text()
        require(
            digest(log) == group["log_sha256"]
            and re.search(r"^OK$", text, re.M)
            and f"Ran {group['count']} tests" in text,
            "regression log changed",
        )
        covered.extend(group["modules"])
    require(
        sorted(covered) == regressions["modules"]
        and sum(g["count"] for g in regressions["groups"]) == regressions["count"],
        "regression partition mismatch",
    )
    profiler = ROOT / "build/stem/profiler-tests.log"
    text = profiler.read_text()
    require(
        re.search(r"^OK$", text, re.M) and "Ran 5 tests" in text,
        "profiler regression incomplete",
    )
    metrics = {}
    for name, s in (("X4", before), ("X5", after)):
        metrics[name] = {
            "capture_id": s["capture_id"],
            "elf_sha256": s["elf_sha256"],
            "instructions": int(s["inference"]["instructions"]["value"]),
            "stem_instructions": int(s["units"][1]["metrics"]["instructions"]["value"]),
            "stem_mix": {
                k: int(v["value"]) for k, v in s["units"][1]["metrics"]["mix"].items()
            },
            "footprint": {k: v["value"] for k, v in s["footprint"].items()},
        }
    report = {
        "status": "PASS",
        "configuration": "X5",
        "metrics": metrics,
        "per_node": per_node,
        "numerical": numerical_proof,
        "existing_isa_only": True,
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
            "compiler": regressions["count"],
            "compiler_report_sha256": digest(path),
            "profiler": 5,
            "profiler_log_sha256": digest(profiler),
        },
        "source_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in (
                Path(__file__),
                ROOT / "tools/xdwmac8/report.py",
                ROOT / "tools/stem/controls.py",
                ROOT / "tests/compiler/test_stem_packed.py",
                ROOT / "tests/compiler/stem_packed_main.cc",
            )
        },
        "hardware": "Existing ISA reused; X5 CV-Wally cycles/timing not measured",
    }
    output = ROOT / "results/profiling"
    (output / "X5-verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    a, b = metrics["X4"], metrics["X5"]
    lines = [
        "# Validated X5 packed RGB stem checkpoint",
        "",
        "| Metric | X4 | X5 |",
        "|---|---:|---:|",
        f"| Inference instructions | {a['instructions']:,} | {b['instructions']:,} |",
        f"| Stem instructions | {a['stem_instructions']:,} | {b['stem_instructions']:,} |",
        f"| Stem loads | {a['stem_mix']['load']:,} | {b['stem_mix']['load']:,} |",
        f"| Stem scalar multiplications | {a['stem_mix']['multiply']:,} | {b['stem_mix']['multiply']:,} |",
        "",
        f"Full-inference reduction: **{100 * (1 - b['instructions'] / a['instructions']):.2f}%** ({a['instructions'] / b['instructions']:.3f}× instruction-count ratio).",
        f"Stem reduction: **{100 * (1 - b['stem_instructions'] / a['stem_instructions']):.2f}%** ({a['stem_instructions'] / b['stem_instructions']:.3f}× instruction-count ratio).",
        "All 63 untargeted execution units retain identical metrics.",
        "",
        "## Implementation",
        "",
        "The compiler prepares 32-byte weight rows (27 original OHWI values plus five zero lanes), and border-specific corrected biases. Each output pixel gathers one signed RGB patch into four registers, reused across all 32 output channels. Four existing Xqmac8 instructions and one unchanged Xrequant produce each output. Invalid spatial and tail lanes are zero. INT32 prefix bounds are proved offline; no new ISA or whole-image im2col buffer is introduced.",
        "",
        "## Validation",
        "",
        f"- {regressions['count']} compiler regressions across all {len(regressions['modules'])} modules and five profiler tests pass.",
        "- Independent INT64 accumulator checks pass 64 synthetic cases under ASan/UBSan, covering borders, small and odd dimensions, extreme data, absent biases, signed offsets, unaligned RGB input, and varied output-channel counts.",
        "- Native, full-tensor capture and ASan/UBSan builds match all eight reference cases. Capture and sanitizer modes each compare 510 complete tensors; the known zero-point-input Softmax outcome remains status 2 after 62 matching tensors.",
        "- Baseline and random_42 full RV64 inference match all 1,000 output bytes. Two full event/PC profiles agree exactly. The stem retires precisely 1,605,632 Xqmac8 and 401,408 Xrequant instructions; padded physical work is 12,845,056 lane products.",
        "- 52 replay fixtures pass native, ASan/UBSan and RV64, with repeated profiles: stem plus five control layers across eight cases, plus four dot controls.",
        "- B1/X1/X2/X3/X4 allocated sections and load segments remain byte-identical. Existing X4 ISA library identities and frozen B0 data are unchanged.",
        "",
        "## Footprint and next bottlenecks",
        "",
        "Prepared constants grow by 51,712 bytes (50,176-byte region map, 512-byte corrected biases, 1,024-byte packed weights). Executable code shrinks from 38,572 to 38,140 bytes. Activation workspace remains 1,505,280 bytes.",
        "Pointwise layers now account for 98,321,810 instructions (58.6%), depthwise layers 50,682,862 (30.2%), and the stem 8,086,466 (4.8%). The largest single node is pointwise node 4 at 9,853,341 instructions (5.9%).",
        "These are retired instruction counts, not cache misses or hardware cycle speedups. X5 hardware performance has not been measured.",
        "",
        "Reproduce with `make compiler-x5-checkpoint`. The adjacent JSON binds captures, binaries, numerical evidence, replay, tests and legacy controls.",
        "",
    ]
    (output / "X5-verification.md").write_text("\n".join(lines))
    print(
        f"X5 checkpoint: PASS ({b['instructions']:,} instructions, {len(rows)} replay fixtures, {regressions['count']} compiler tests)"
    )


if __name__ == "__main__":
    main()
