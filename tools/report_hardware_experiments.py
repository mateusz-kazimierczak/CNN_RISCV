#!/usr/bin/env python3
"""Build the submission hardware progression from verified Spike/RTL evidence."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from compiler.build_evidence import canonical, digest
from tools.hardware_experiments import (
    MANIFEST,
    RESULTS,
    artifact,
    custom_counts,
    load_capture,
    read,
    require,
    same_loaded_program,
    stages,
    validate_compatible,
    validate_selection,
    validate_transition,
)
from tools.hardware_rtl_evidence import validate_hardware_reuse, validate_rtl
from tools.report_b1_software import family

OUTPUT = RESULTS / "hardware-progression"
SUBMISSION = ROOT / "results/submission"


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def reduction(before, after):
    return 100 * (before - after) / before


def plot(rows, key, output, title, xlabel, note):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with plt.rc_context(
        {"svg.fonttype": "none", "svg.hashsalt": output.name, "font.size": 11}
    ):
        fig, ax = plt.subplots(
            figsize=(10.8, max(5.2, len(rows) * 0.43 + 1.5)), layout="constrained"
        )
        values = [r[key] / 1e9 for r in rows]
        bars = ax.barh(
            range(len(rows)),
            values,
            color=[
                "#087f8c" if i == len(rows) - 1 else "#637587" for i in range(len(rows))
            ],
            height=0.65,
        )
        ax.set_yticks(range(len(rows)), [f"{r['stage']}  {r['title']}" for r in rows])
        ax.invert_yaxis()
        maximum = max(values)
        for bar, value in zip(bars, values):
            ax.text(
                value + maximum * 0.012,
                bar.get_y() + bar.get_height() / 2,
                f"{value:.3f}",
                va="center",
                fontsize=10,
            )
        ax.set_xlim(0, maximum * 1.15)
        ax.set_xlabel(xlabel, labelpad=10)
        ax.set_title(title, loc="left", weight="bold", pad=16)
        ax.xaxis.grid(True, alpha=0.18)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.tick_params(axis="y", length=0, pad=10)
        fig.get_layout_engine().set(rect=(0, 0.065, 1, 0.935))
        fig.text(0.025, 0.015, note, fontsize=8.5)
        svg_path = output.with_suffix(".svg")
        fig.savefig(svg_path, metadata={"Date": None})
        svg_path.write_text(
            "\n".join(line.rstrip() for line in svg_path.read_text().splitlines()) + "\n"
        )
        fig.savefig(output.with_suffix(".png"), dpi=180)
        fig.savefig(
            output.with_suffix(".pdf"), metadata={"CreationDate": None, "ModDate": None}
        )
        plt.close(fig)


def resolve_paths():
    index_path = OUTPUT / "captures.json"
    if not index_path.exists():
        return {s["id"]: RESULTS / s["source"] / "summary.json" for s in stages()}
    index = read(index_path)
    require(
        index["complete"] and index["manifest_sha256"] == digest(MANIFEST),
        "hardware capture index is incomplete or stale",
    )
    require(
        [r["stage"] for r in index["stages"]] == [s["id"] for s in stages()],
        "capture index stage inventory differs",
    )
    paths = {}
    for row in index["stages"]:
        path = ROOT / row["summary"]
        require(digest(path) == row["summary_sha256"], "indexed summary changed")
        paths[row["stage"]] = path
    return paths


def generate():
    bundles, rtl, rows, identities = {}, {}, [], []
    node_rows, mix_rows, footprint_rows, custom_rows = [], [], [], []
    paths = resolve_paths()
    for stage in stages():
        print(f"Revalidating {stage['id']}", flush=True)
        bundle = load_capture(paths[stage["id"]])
        validate_selection(stage, bundle)
        summary = bundle["summary"]
        require(
            summary["gates"]
            == {
                "repeat_histograms_identical": True,
                "per_pc_partition": True,
                "full_output_bytes_compared": 1000,
                "observed_execution_units": 64,
            },
            "incomplete capture gates",
        )
        count = int(summary["inference"]["instructions"]["value"])
        parent = bundles.get(stage["parent"])
        changed = validate_transition(stage, parent, bundle) if parent else []
        before = (
            int(parent["summary"]["inference"]["instructions"]["value"])
            if parent
            else count
        )
        rows.append(
            {
                "stage": stage["id"],
                "parent": stage["parent"] or "",
                "title": stage["title"],
                "kind": stage["kind"],
                "presentation": stage.get("presentation", ""),
                "main_title": stage.get("presentation_title", stage["title"]),
                "instructions": count,
                "instructions_removed": before - count,
                "reduction_pct": reduction(before, count),
                "checkpoint": summary["checkpoint"],
                "capture_id": summary["capture_id"],
            }
        )
        mix = {k: int(v["value"]) for k, v in summary["inference"]["mix"].items()}
        require(
            sum(mix.values()) == count, "instruction mix does not conserve inference"
        )
        custom = custom_counts(summary)
        postinc = sum(
            int(v["value"])
            for v in summary["inference"].get("postincrement", {}).values()
        )
        require(
            sum(custom.values()) == mix["custom"] + postinc,
            "custom utilization disagrees with classified mix",
        )
        macs = int(summary["inference"]["logical_macs"]["value"])
        mix_rows.append(
            {
                "stage": stage["id"],
                **mix,
                "memory_instructions": mix["load"] + mix["store"],
                "logical_macs_per_instruction": macs / count,
                "memory_instructions_per_logical_mac": (mix["load"] + mix["store"])
                / macs,
                "all_custom_encoding_instructions": sum(custom.values()),
                "all_custom_frequency": sum(custom.values()) / count,
            }
        )
        custom_rows.append(
            {
                "stage": stage["id"],
                **{
                    name: custom.get(name, 0)
                    for name in (
                        "xqmac8",
                        "xrequant",
                        "xpostinc_load",
                        "xpostinc_store",
                        "xdwmac8",
                        "xdwset0",
                        "xdwset1",
                        "xdwset2",
                        "xdwset3",
                        "xdwget0",
                        "xdwget1",
                        "xdwget2",
                        "xdwget3",
                    )
                },
            }
        )
        graph = bundle["verified"][2]
        old = (
            {tuple(u["nodes"]): u for u in parent["summary"]["units"]} if parent else {}
        )
        total = 0
        for unit in summary["units"]:
            require(len(unit["nodes"]) == 1, "expected one unit per logical node")
            node = unit["nodes"][0]
            m = unit["metrics"]
            n = int(m["instructions"]["value"])
            total += n
            prior = int(old[(node,)]["metrics"]["instructions"]["value"]) if old else n
            node_rows.append(
                {
                    "stage": stage["id"],
                    "node": node,
                    "family": family(graph, graph.nodes[node]),
                    "implementation": unit["implementation"],
                    "instructions": n,
                    "instructions_removed": prior - n,
                    "load": int(m["mix"]["load"]["value"]),
                    "store": int(m["mix"]["store"]["value"]),
                }
            )
        require(
            total + int(summary["overhead"]["instructions"]["value"]) == count,
            "operator totals do not conserve inference",
        )
        footprint_rows.append(
            {
                "stage": stage["id"],
                **{
                    k: v["value"]
                    for k, v in summary["footprint"].items()
                    if k != "hardware_cycles"
                },
            }
        )
        recorded_parent = bundle["directory"] / "parent-summary.json"
        identities.append(
            {
                "stage": stage["id"],
                "comparison_parent": stage["parent"],
                "changed_nodes": changed,
                "recorded_capture_parent": read(recorded_parent)["capture_id"]
                if recorded_parent.exists()
                else None,
                "comparison_parent_capture": parent["summary"]["capture_id"]
                if parent
                else None,
                "summary": str(bundle["summary_path"].relative_to(ROOT)),
                "summary_sha256": digest(bundle["summary_path"]),
                "capture_id": summary["capture_id"],
                "elf_sha256": summary["elf_sha256"],
                "kernel_plan_sha256": digest(artifact(bundle, "kernel_plan.json")),
                "build_evidence_sha256": summary["build_evidence_sha256"],
            }
        )
        if stage.get("rtl"):
            rtl_bundle = bundle
            rtl_summary = read(ROOT / stage["rtl"]["summary"])["runs"][
                stage["presentation"]
            ]
            if summary["elf_sha256"] != rtl_summary["elf_sha256"]:
                # Fresh builds may change non-loaded debug/build metadata.
                # Bind cycles to the exact archived RTL ELF, then certify loaded
                # program equality; never transfer cycles on count equality alone.
                rtl_bundle = load_capture(RESULTS / stage["source"] / "summary.json")
                require(
                    same_loaded_program(bundle, rtl_bundle),
                    "fresh build differs from exact RTL workload program",
                )
            rtl[stage["presentation"]] = validate_rtl(stage, rtl_bundle)
            rtl[stage["presentation"]].update(
                selected_elf_sha256=summary["elf_sha256"],
                selected_program_loaded_bytes_identical=True,
            )
        bundles[stage["id"]] = bundle
    validate_hardware_reuse(rtl["X4"], rtl["X5"])
    bridge = load_capture(ROOT / read(MANIFEST)["software_bridge"])
    validate_compatible(bridge["summary"], bundles["B1"]["summary"])
    for key in ("inference", "footprint"):
        require(
            bridge["summary"][key] == bundles["B1"]["summary"][key],
            f"B1.7/accepted B1 mismatch: {key}",
        )
    require(
        same_loaded_program(bridge, bundles["B1"]),
        "B1.7 and RTL B1 differ in loaded bytes/layout",
    )
    main, cycles = [], []
    for row in rows:
        if not row["presentation"]:
            continue
        before = main[-1]["instructions"] if main else row["instructions"]
        group_kind = {
            "X1": "isa_and_compiler_tuning",
            "X2": "isa_and_compiler_tuning",
            "X4": "software_control_and_isa",
        }.get(row["presentation"], row["kind"])
        main.append(
            {
                **row,
                "stage": row["presentation"],
                "title": row["main_title"],
                "kind": group_kind,
                "parent": main[-1]["stage"] if main else "",
                "instructions_removed": before - row["instructions"],
                "reduction_pct": reduction(before, row["instructions"]),
            }
        )
        r = rtl[row["presentation"]]
        prior = cycles[-1]["cycles"] if cycles else r["cycles"]
        cycles.append(
            {
                "stage": row["presentation"],
                "title": row["main_title"],
                "instructions": r["instructions"],
                "cycles": r["cycles"],
                "cpi": r["cpi"],
                "cycles_removed": prior - r["cycles"],
                "cycle_reduction_pct": reduction(prior, r["cycles"]),
                "cycle_speedup": prior / r["cycles"],
                "elf_sha256": r["elf_sha256"],
                "source_summary": r["source_summary"],
            }
        )
    operator_rows = []
    for stage in stages():
        families = Counter()
        savings = Counter()
        for r in node_rows:
            if r["stage"] == stage["id"]:
                families[r["family"]] += r["instructions"]
                savings[r["family"]] += r["instructions_removed"]
        for name, n in sorted(families.items()):
            operator_rows.append(
                {
                    "stage": stage["id"],
                    "family": name,
                    "instructions": n,
                    "instructions_removed": savings[name],
                }
            )
    OUTPUT.mkdir(exist_ok=True)
    for name, data in (
        ("stages", rows),
        ("presentation", main),
        ("cycles", cycles),
        ("instruction-mix", mix_rows),
        ("custom-utilization", custom_rows),
        ("nodes", node_rows),
        ("operators", operator_rows),
        ("footprint", footprint_rows),
    ):
        write_csv(OUTPUT / (name + ".csv"), data)
    plot(
        main,
        "instructions",
        OUTPUT / "instruction-progression",
        "Custom-ISA optimization progression",
        "Retired instructions per inference (billions)",
        "X1/X2 include compiler tuning; X4 includes measured D1 software correction. X5 adds no ISA.",
    )
    plot(
        cycles,
        "cycles",
        OUTPUT / "cycle-progression",
        "Accepted full-model CV-Wally simulations",
        "Simulated cycles per inference (billions)",
        "Archived RTL measurements; D1 has no full-model cycle result. Physical Fmax and area are unavailable.",
    )
    validation = {
        "schema_version": 1,
        "manifest_sha256": digest(MANIFEST),
        "software_manifest_sha256": digest(ROOT / read(MANIFEST)["software_manifest"]),
        "generator_sha256": digest(Path(__file__)),
        "validator_sha256": digest(ROOT / "tools/hardware_experiments.py"),
        "rtl_validator_sha256": digest(ROOT / "tools/hardware_rtl_evidence.py"),
        "captures": identities,
        "rtl": rtl,
        "software_bridge_capture": bridge["summary"]["capture_id"],
        "checks": {
            "frozen_capture_integrity": True,
            "explicit_production_plans": True,
            "comparison_compatibility": True,
            "operator_and_mix_conservation": True,
            "full_output_and_repeat_agreement": True,
            "D1_X4_equal_prepared_data": True,
            "X5_same_hardware_as_X4": True,
            "B1_7_same_loaded_program_as_RTL_B1": True,
        },
        "limits": {
            "new_RTL_runs": False,
            "D1_cycles": None,
            "physical_fmax": None,
            "area": None,
        },
    }
    (OUTPUT / "validation.json").write_text(canonical(validation))
    write_readme(rows, main, cycles, bundles)
    write_submission(main, cycles, validation)
    print(f"Validated hardware/submission reports: {OUTPUT} and {SUBMISSION}")


def write_readme(rows, main, cycles, bundles):
    lines = [
        "# Hardware-era optimization progression",
        "",
        "Generated by `gmake hardware-report` from explicit configurations and revalidated immutable Spike/archived RTL evidence.",
        "",
        "![Instruction progression](instruction-progression.svg)",
        "",
        "| Main stage | Retired instructions | Reduction from accepted parent | Simulated cycles | Cycle reduction | CPI |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row, r in zip(main, cycles):
        lines.append(
            f"| {row['stage']} | {row['instructions']:,} | {row['reduction_pct']:.3f}% | {r['cycles']:,} | {r['cycle_reduction_pct']:.3f}% | {r['cpi']:.4f} |"
        )
    lines += [
        "",
        "Main X1 and X2 include their compiler refinements. Main X4 compares against X3 and includes D1. X5 changes the stem software using existing Xqmac8; it adds no hardware instruction.",
        "",
        "![Cycle progression](cycle-progression.svg)",
        "",
        "## Measured substages and controls",
        "",
        "| Stage | Comparison parent | Change | Kind | Retired instructions | Removed | Reduction |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['stage']} | {row['parent'] or '—'} | {row['title']} | {row['kind']} | {row['instructions']:,} | {row['instructions_removed']:,} | {row['reduction_pct']:.3f}% |"
        )
    start, end = main[0]["instructions"], main[-1]["instructions"]
    lines += [
        "",
        f"B1 → X5 removes {reduction(start, end):.3f}% of retired instructions ({start / end:.3f}× instruction-count ratio) and gives {cycles[0]['cycles'] / cycles[-1]['cycles']:.3f}× simulated cycle speedup. This is not a physical execution-time or performance/area result.",
        "",
        "D1 is a software-only control with no separate full-model RTL cycles in the archived records. X4's ISA-only instruction comparison is D1 → X4; its main-stage cycle comparison is X3 → X4. Never assign D1 a zero or interpolated cycle count.",
        "",
        "X3.broad and selected X3 are alternatives from the same optimized X2 parent. They are not sequential cumulative stages. X2.2 is a new production-compiler measurement; it reproduces the historical outlining prototype at 436,487,389 instructions. Prototype investigations remain separate historical evidence.",
        "",
        "## Evidence and interpretation",
        "",
        "`stages.csv` records explicit comparison edges; `presentation.csv` groups the accepted main stages. `cycles.csv` records only measured accepted RTL configurations. `instruction-mix.csv`, `custom-utilization.csv`, `operators.csv`, `nodes.csv` and `footprint.csv` expose opcode use, affected operators, regressions and storage cost. Every table identifies stages from `experiments/hardware.json`.",
        "",
        "The preserved capture's original parent is retained in `validation.json` alongside the submission comparison parent. Existing captures are not renamed or rewritten. Comparisons are recomputed after checking the same model, input, boundary and logical node identities; X2.3 and X4 therefore retain their historical capture parents while their incremental comparisons use X2.2 and D1.",
        "",
        "All stages have complete 1,000-byte canonical output checks, two identical event/PC captures, and exactly 64 conserving execution units. Every frozen plan must equal the production selector's reconstruction from the manifest. Original summary reporter-version hashes may differ from the current reporter; every other summary field must reproduce exactly.",
        "",
        "Archived RTL PASS records are checked against selected ELF hashes, workload contracts, per-opcode retirements, monitor gates and simulator identities. Custom-stage output bytes are decoded and rehashed from local archived snapshots. The baseline B1 archive retains the output hash/PASS record rather than raw bytes. These are revalidated existing RTL measurements; this report does not claim new RTL runs.",
        "",
        "Post-increment instructions remain in the load/store mix and are also counted in custom utilization; do not add custom frequency back into the instruction-mix total. Loads/stores are instruction counts, not cache misses or external traffic. Ratios, CPI, deltas and artifact sizes are derived from measured evidence.",
        "",
        "Physical Fmax, mapped area and speedup/area remain unavailable because synthesis is blocked at DC startup. See `results/synthesis/baseline/README.md`. Raw captures and RTL snapshots remain in ignored `build/`; their identities are recorded in `validation.json`.",
        "",
        "Reproduction: `gmake hardware-experiments` verifies retained evidence and runs gates; `gmake hardware-recapture` creates distinct fresh Spike builds/captures without overwriting history. `gmake hardware-report` regenerates reports only. RTL setup, directed/replay commands and full-model run/collection instructions remain in `docs/cvw-verilator.md` and the extension-specific guides.",
        "",
        "Figures are available as SVG, PNG and PDF: `instruction-progression.*` and `cycle-progression.*`. The unified A0 → B1.1–B1.7 → X1–X5 package is in `results/submission/`.",
        "",
    ]
    (OUTPUT / "README.md").write_text("\n".join(lines))


def write_submission(main, cycles, hardware_validation):
    software = RESULTS / "B1-reordered"
    verification = read(software / "validation.json")
    require(
        verification["manifest_sha256"]
        == hardware_validation["software_manifest_sha256"]
        and all(verification["checks"].values()),
        "software report validation is stale or failed",
    )
    with (software / "presentation.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    software_spec = read(ROOT / read(MANIFEST)["software_manifest"])
    require(
        verification["baseline"] == software_spec["baseline"]
        and rows[0]["checkpoint"] == software_spec["baseline"]["checkpoint"],
        "software baseline label/evidence mapping differs",
    )
    require(
        [r["stage"] for r in rows]
        == [software_spec["baseline"]["id"], *[s["id"] for s in software_spec["stages"] if s["present"]]],
        "software presentation inventory differs",
    )
    baseline = read(RESULTS / "B0/summary.json")
    require(
        digest(RESULTS / "B0/summary.json") == verification["B0_summary_sha256"],
        "frozen software baseline summary changed",
    )
    require(
        int(rows[0]["instructions"]) == baseline["inference"]["instructions"],
        "A0 (historical B0) presentation count differs",
    )
    software_ids = {s["stage"]: s["capture_id"] for s in verification["captures"]}
    for row in rows[1:]:
        validated = load_capture(RESULTS / row["checkpoint"] / "summary.json")[
            "summary"
        ]
        require(
            validated["capture_id"] == row["capture_id"] == software_ids[row["stage"]],
            "software presentation capture differs",
        )
        require(
            int(row["instructions"])
            == int(validated["inference"]["instructions"]["value"]),
            "software presentation count differs",
        )
    unified = [
        {
            "stage": r["stage"],
            "title": r["title"],
            "instructions": int(r["instructions"]),
            "checkpoint": r["checkpoint"],
            "capture_id": r["capture_id"],
        }
        for r in rows
    ]
    unified += [
        {
            k: r[k]
            for k in ("stage", "title", "instructions", "checkpoint", "capture_id")
        }
        for r in main[1:]
    ]
    for i, row in enumerate(unified):
        before = unified[i - 1]["instructions"] if i else row["instructions"]
        row.update(
            instructions_removed=before - row["instructions"],
            reduction_pct=reduction(before, row["instructions"]),
        )
    SUBMISSION.mkdir(exist_ok=True)
    write_csv(SUBMISSION / "progression.csv", unified)
    plot(
        unified,
        "instructions",
        SUBMISSION / "instruction-progression",
        "Complete submission progression",
        "Retired instructions per canonical inference (billions)",
        "B1.5 groups stem/runtime cleanup; X1/X2 group compiler tuning; X4 includes D1; X5 adds no ISA.",
    )
    (SUBMISSION / "validation.json").write_text(
        canonical(
            {
                "schema_version": 1,
                "software_validation_sha256": digest(software / "validation.json"),
                "hardware_validation_sha256": digest(OUTPUT / "validation.json"),
                "progression_sha256": digest(SUBMISSION / "progression.csv"),
                "scope": "combined software/custom-ISA retirement profiles and archived full-model RTL cycles; physical area/Fmax unavailable",
            }
        )
    )
    lines = [
        "# Combined Spike and RTL results",
        "",
        "A0 is frozen LiteRT Micro (historical evidence/configuration name B0); B1.1 is the custom compiler (historical config A0). Accepted B1 means final B1.7. Existing capture identities are unchanged.",
        "",
        "The main progression is **A0 → B1.1 → B1.2 → B1.3 → B1.5 → B1.6 → B1.7 → X1 → X2 → X3 → X4 → X5**.",
        "",
        "![Complete submission progression](instruction-progression.svg)",
        "",
        "| Stage | Change | Retired instructions | Reduction from preceding presentation stage |",
        "|---|---|---:|---:|",
    ]
    for row in unified:
        lines.append(
            f"| {row['stage']} | {row['title']} | {row['instructions']:,} | {row['reduction_pct']:.3f}% |"
        )
    lines += [
        "",
        "## Supporting measurements",
        "",
        "- [Software stages and footprint](../profiling/B1-reordered/README.md): B1.4 remains measured independently and is grouped into B1.5 in the main presentation.",
        "- [Hardware-era stages, ablations, opcode use and cycles](../profiling/hardware-progression/README.md): X1.1–X1.4 and X2.1–X2.3 remain measured; X3.broad is an alternative trial; D1 isolates software correction before X4.",
        "- [Design map](../../DESIGN.md), [experiment index](../../EXPERIMENTS.md), [evaluation scopes and artifacts](../../docs/submission.md).",
        "",
        "Accepted hardware-era configurations have full-model RTL cycles; D1 and the intermediate software/compiler stages do not acquire cycle results by interpolation. X5 reuses the exact X4 RTL simulator. Physical Fmax and mapped area are unavailable. The [midterm results](../midterm/README.md) provide the separate Spike-only evaluation.",
        "",
        "Run `gmake submission-report` to regenerate and cross-check the software, hardware and unified evidence package. `gmake hardware-experiments` runs hardware-era verification gates and revalidates retained captures; `gmake hardware-recapture` explicitly generates separate fresh Spike captures. Hardware full-model reruns use the pinned Linux/WSL workflow and exact workload contracts in the RTL guide.",
        "",
    ]
    (SUBMISSION / "README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    generate()
