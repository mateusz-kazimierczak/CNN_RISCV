#!/usr/bin/env python3
"""Revalidate cumulative software captures and produce submission tables/chart."""

from __future__ import annotations

import collections
import csv
import io
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from compiler.build_evidence import canonical, digest
from tools.profile_compiler import make_summary, verify_capture
from tools.report_b1_software import family
from tools.run_software_experiments import (
    CAPTURES,
    MANIFEST,
    RESULTS,
    stages,
    verify_correctness,
)

OUTPUT = RESULTS / "B1-reordered"


def count(summary):
    return int(summary["inference"]["instructions"]["value"])


def write_csv(path, rows):
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def comparison(before, after):
    return {
        "instructions_removed": before - after,
        "reduction_pct": 100 * (before - after) / before,
    }


def validate_parent(directory, parent_directory, previous_summary):
    saved = json.loads((directory / "parent-summary.json").read_text())
    if saved != previous_summary:
        raise ValueError("capture parent differs from previous stage")
    identity = (directory / "parent-identity.txt").read_text().strip()
    if identity != digest(parent_directory / "manifest.json"):
        raise ValueError("parent identity mismatch")


def chart(rows, output=None):
    """Publication exports from the same seven measured presentation rows."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    shown = [row for row in rows if row["present"]]
    with plt.rc_context(
        {"svg.fonttype": "none", "svg.hashsalt": "software-sequence", "font.size": 11}
    ):
        fig, ax = plt.subplots(figsize=(10.8, 5.9), layout="constrained")
        values = [row["instructions"] / 1e9 for row in shown]
        colors = ["#087f8c" if row["stage"] == "B1.7" else "#637587" for row in shown]
        bars = ax.barh(range(len(shown)), values, color=colors, height=0.65)
        ax.set_yticks(
            range(len(shown)), [f"{row['stage']}  {row['title']}" for row in shown]
        )
        ax.invert_yaxis()
        for bar, value in zip(bars, values):
            ax.text(
                value + 0.04,
                bar.get_y() + bar.get_height() / 2,
                f"{value:.3f}",
                va="center",
                fontsize=10,
            )
        ax.set_xlim(0, 5.4)
        ax.set_xlabel(
            "Retired instructions per canonical inference (billions)", labelpad=10
        )
        ax.set_title(
            "Cumulative software optimization", loc="left", weight="bold", pad=18
        )
        ax.xaxis.grid(True, alpha=0.18)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.tick_params(axis="y", length=0, pad=10)
        fig.get_layout_engine().set(rect=(0, 0.055, 1, 0.945))
        fig.text(
            0.025,
            0.018,
            "B1.5 includes measured B1.4 stem unrolling. Instruction counts are not hardware cycle speedup.",
            fontsize=9,
        )
        svg = io.StringIO()
        fig.savefig(svg, format="svg", metadata={"Date": None})
        if output:
            fig.savefig(output / "optimization-history.png", dpi=180)
            fig.savefig(
                output / "optimization-history.pdf",
                metadata={"CreationDate": None, "ModDate": None},
            )
        plt.close(fig)
    return "\n".join(line.rstrip() for line in svg.getvalue().splitlines()) + "\n"


def generate():
    baseline = json.loads(MANIFEST.read_text())["baseline"]
    if baseline["id"] != "A0" or baseline["checkpoint"] != "B0":
        raise ValueError("baseline must select frozen LiteRT evidence")
    b0_path = RESULTS / "B0/summary.json"
    contract = json.loads((ROOT / "tools/compiler/baseline.json").read_text())
    frozen = contract["frozen_files"]["results/profiling/B0/summary.json"]
    if digest(b0_path) != (frozen["sha256"] if isinstance(frozen, dict) else frozen):
        raise ValueError("frozen B0 changed")
    b0 = json.loads(b0_path.read_text())
    b0_count = b0["inference"]["instructions"]
    rows = [
        {
            "stage": baseline["id"],
            "title": baseline["title"],
            "checkpoint": "B0",
            "instructions": b0_count,
            "instructions_removed": 0,
            "reduction_pct": 0.0,
            "reduction_from_A0_pct": 0.0,
            "present": True,
            "capture_id": "",
        }
    ]
    b0_mix = b0["inference"]["mix"]
    if sum(b0_mix.values()) != b0_count:
        raise ValueError("B0 mix does not conserve inference")
    mix_rows = [
        {
            "stage": baseline["id"],
            **b0_mix,
            "memory_instructions": b0["inference"]["memory_instructions"],
            "logical_macs_per_instruction": b0["inference"]["logical_macs"] / b0_count,
            "memory_instructions_per_logical_mac": b0["inference"][
                "memory_instructions"
            ]
            / b0["inference"]["logical_macs"],
        }
    ]
    operator_rows, node_rows, footprint_rows, identities = [], [], [], []
    function_rows = []
    scaling_rows = [
        {
            "stage": baseline["id"],
            "out_of_line_scaling_body_instructions": b0["inference"][
                "fixed_point_scaling_helper_body_instructions"
            ],
            "scope": "exclusive helper bodies only; excludes inline arithmetic and caller work",
        }
    ]
    previous, previous_capture, reference = b0_count, None, None
    previous_nodes = {n["index"]: n["instructions"] for n in b0["layers"]}
    previous_families = None
    summaries = []
    for stage in stages():
        result = RESULTS / stage["checkpoint"]
        receipt = json.loads((result / "experiment.json").read_text())
        expected = {
            "manifest_sha256": digest(MANIFEST),
            "stage": stage,
            "parent_capture_id": previous_capture,
        }
        if receipt["selection"] != expected:
            raise ValueError(f"stage selection or lineage differs: {stage['id']}")
        correctness = verify_correctness(ROOT / "build/compiler" / stage["checkpoint"])
        directory = CAPTURES / receipt["capture_id"]
        verified = verify_capture(directory)
        summary = make_summary(directory, verified)
        if summary != json.loads((result / "summary.json").read_text()):
            raise ValueError(f"saved summary differs: {stage['id']}")
        if previous_capture:
            validate_parent(directory, CAPTURES / previous_capture, summaries[-1])
        identity = (
            summary["model_sha256"],
            summary["input"],
            summary["boundary_policy"],
        )
        if reference is not None and reference != identity:
            raise ValueError("model/input/boundary mismatch")
        reference = identity
        if (
            b0["provenance"]["hashes"]["model"] != identity[0]
            or b0["provenance"]["input_seed"] != 1
        ):
            raise ValueError("B0 model/input mismatch")
        if summary["gates"] != {
            "repeat_histograms_identical": True,
            "per_pc_partition": True,
            "full_output_bytes_compared": 1000,
            "observed_execution_units": 64,
        }:
            raise ValueError("capture acceptance gates differ")
        current = count(summary)
        rows.append(
            {
                "stage": stage["id"],
                "title": stage["title"],
                "checkpoint": stage["checkpoint"],
                "instructions": current,
                **comparison(previous, current),
                "reduction_from_A0_pct": comparison(b0_count, current)["reduction_pct"],
                "present": stage["present"],
                "capture_id": summary["capture_id"],
            }
        )
        mix = {k: int(v["value"]) for k, v in summary["inference"]["mix"].items()}
        if sum(mix.values()) != current or mix["custom"]:
            raise ValueError("nonconserving or custom software instruction mix")
        mix_rows.append(
            {
                "stage": stage["id"],
                **mix,
                "memory_instructions": int(
                    summary["inference"]["memory_instructions"]["value"]
                ),
                "logical_macs_per_instruction": 385187552 / current,
                "memory_instructions_per_logical_mac": (mix["load"] + mix["store"])
                / 385187552,
            }
        )
        scaling = 0
        for function in summary["functions"]:
            n = int(function["instructions"]["value"])
            function_rows.append(
                {
                    "stage": stage["id"],
                    "function": function["function"],
                    "instructions": n,
                    "scope": "exclusive_function_body",
                }
            )
            if function["function"].startswith(
                (
                    "tflite::MultiplyByQuantizedMultiplier(",
                    "arch_project::numeric::multiply(",
                    "arch_project::numeric::multiply_nonpositive(",
                )
            ):
                scaling += n
        scaling_rows.append(
            {
                "stage": stage["id"],
                "out_of_line_scaling_body_instructions": scaling,
                "scope": "exclusive helper bodies only; excludes inline arithmetic and caller work",
            }
        )
        graph = verified[2]
        if previous_families is None:
            previous_families = collections.Counter()
            for node in b0["layers"]:
                name = family(graph, graph.nodes[node["index"]])
                previous_families[name] += node["instructions"]
                node_rows.append(
                    {
                        "stage": baseline["id"],
                        "node": node["index"],
                        "family": name,
                        "implementation": "frozen_litert_reference",
                        "instructions": node["instructions"],
                        "instructions_removed": "",
                        "load": node["mix"]["load"],
                        "store": node["mix"]["store"],
                    }
                )
            previous_families["Invocation overhead"] = b0["inference"][
                "interpreter_overhead_instructions"
            ]
            if sum(previous_families.values()) != b0_count:
                raise ValueError("B0 operator totals do not conserve inference")
            for name, n in sorted(previous_families.items()):
                operator_rows.append(
                    {
                        "stage": baseline["id"],
                        "family": name,
                        "instructions": n,
                        "instructions_removed": "",
                    }
                )
            footprint_rows.append(
                {
                    "stage": baseline["id"],
                    **{k: None for k in summary["footprint"] if k != "hardware_cycles"},
                }
            )
            footprint_rows[0].update(
                executable_code=b0["provenance"]["footprint"]["executable_code_bytes"],
                bss=b0["provenance"]["footprint"]["bss_bytes"],
                initialized_writable=b0["provenance"]["footprint"][
                    "initialized_writable_bytes"
                ],
                readonly=b0["provenance"]["footprint"]["model_bytes"]
                + b0["provenance"]["footprint"]["other_readonly_bytes"],
            )
        families = collections.Counter()
        nodes = {}
        for unit in summary["units"]:
            if len(unit["nodes"]) != 1:
                raise ValueError(
                    "software comparison requires one unit per logical node"
                )
            node = unit["nodes"][0]
            name = family(graph, graph.nodes[node])
            n = int(unit["metrics"]["instructions"]["value"])
            families[name] += n
            nodes[node] = n
            node_rows.append(
                {
                    "stage": stage["id"],
                    "node": node,
                    "family": name,
                    "implementation": unit["implementation"],
                    "instructions": n,
                    "instructions_removed": previous_nodes[node] - n
                    if previous_nodes
                    else "",
                    "load": int(unit["metrics"]["mix"]["load"]["value"]),
                    "store": int(unit["metrics"]["mix"]["store"]["value"]),
                }
            )
        overhead = int(summary["overhead"]["instructions"]["value"])
        if sum(families.values()) + overhead != current:
            raise ValueError("operator totals do not conserve inference")
        families["Invocation overhead"] = overhead
        for name, n in sorted(families.items()):
            operator_rows.append(
                {
                    "stage": stage["id"],
                    "family": name,
                    "instructions": n,
                    "instructions_removed": previous_families[name] - n
                    if previous_families
                    else "",
                }
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
        # Compact portable native/sanitizer coverage, tied to build/report hashes.
        (result / "verification.json").write_text(canonical(correctness))
        identities.append(
            {
                "stage": stage["id"],
                "capture_id": summary["capture_id"],
                "elf_sha256": summary["elf_sha256"],
                "build_evidence_sha256": summary["build_evidence_sha256"],
                "experiment_receipt_sha256": digest(result / "experiment.json"),
                "native_verification_sha256": digest(result / "verification.json"),
            }
        )
        summaries.append(summary)
        previous, previous_capture, previous_nodes, previous_families = (
            current,
            summary["capture_id"],
            nodes,
            families,
        )

    accepted_saved = json.loads((RESULTS / "B1-software/summary.json").read_text())
    accepted_dir = CAPTURES / accepted_saved["capture_id"]
    accepted = make_summary(accepted_dir, verify_capture(accepted_dir))
    if summaries[-1]["inference"] != accepted["inference"]:
        raise ValueError("B1.7 does not reproduce accepted B1 inference metrics")
    # Each unit and all memory-plan storage metrics must also reproduce.
    if summaries[-1]["footprint"] != accepted["footprint"]:
        raise ValueError("B1.7 footprint differs from accepted B1")
    if [u["metrics"] for u in summaries[-1]["units"]] != [
        u["metrics"] for u in accepted["units"]
    ]:
        raise ValueError("B1.7 operator metrics differ from accepted B1")
    presentation = []
    for row in rows:
        if row["present"]:
            last = (
                presentation[-1]["instructions"]
                if presentation
                else row["instructions"]
            )
            presentation.append({**row, **comparison(last, row["instructions"])})
    focus_rows = []
    focus = {
        "B1.1": None,
        "B1.2": ("Pointwise convolution",),
        "B1.3": ("Depthwise 3x3", "Depthwise 5x5"),
        "B1.4": ("Stem convolution",),
        "B1.5": None,
        "B1.6": (
            "Pointwise convolution",
            "Depthwise 3x3",
            "Depthwise 5x5",
            "Stem convolution",
        ),
        "B1.7": ("Pointwise convolution",),
    }
    for before, after in itertools.pairwise(rows):
        selected = focus[after["stage"]]
        old = [
            r
            for r in node_rows
            if r["stage"] == before["stage"]
            and (selected is None or r["family"] in selected)
        ]
        new = [
            r
            for r in node_rows
            if r["stage"] == after["stage"]
            and (selected is None or r["family"] in selected)
        ]
        removed = sum(r["instructions"] for r in old) - sum(
            r["instructions"] for r in new
        )
        memory_removed = sum(r["load"] + r["store"] for r in old) - sum(
            r["load"] + r["store"] for r in new
        )
        focus_rows.append(
            {
                "stage": after["stage"],
                "focus": ", ".join(selected)
                if selected
                else (
                    "All operators (custom compilation)"
                    if after["stage"] == "B1.1"
                    else "All operators (grouped runtime)"
                ),
                "focus_instructions_removed": removed,
                "other_instructions_removed": after["instructions_removed"] - removed,
                "focus_memory_instructions_removed": memory_removed,
            }
        )
    OUTPUT.mkdir(exist_ok=True)
    for filename, data in (
        ("stages.csv", rows),
        ("presentation.csv", presentation),
        ("instruction-mix.csv", mix_rows),
        ("operators.csv", operator_rows),
        ("nodes.csv", node_rows),
        ("footprint.csv", footprint_rows),
        ("functions.csv", function_rows),
        ("scaling-helpers.csv", scaling_rows),
        ("focus.csv", focus_rows),
    ):
        write_csv(OUTPUT / filename, data)
    (OUTPUT / "optimization-history.svg").write_text(chart(rows, OUTPUT))
    (OUTPUT / "validation.json").write_text(
        canonical(
            {
                "schema_version": 2,
                "baseline": baseline,
                "manifest_sha256": digest(MANIFEST),
                "report_generator_sha256": digest(Path(__file__)),
                "runner_sha256": digest(ROOT / "tools/run_software_experiments.py"),
                "report_requirements_sha256": digest(
                    ROOT / "experiments/requirements.txt"
                ),
                "B0_summary_sha256": digest(b0_path),
                "B0_capture_hashes": b0["provenance"]["capture_sha256"],
                "captures": identities,
                "accepted_reference_capture": accepted["capture_id"],
                "checks": {
                    "frozen_B0": True,
                    "capture_integrity": True,
                    "parent_lineage": True,
                    "model_input_boundary_compatible": True,
                    "operator_and_mix_conservation": True,
                    "byte_exact_output_and_repeat_agreement": True,
                    "accepted_B1_reproduced": True,
                },
            }
        )
    )
    lines = [
        "# Cumulative software optimization results",
        "",
        "Generated by `gmake software-report` from validated captures and `experiments/software.json`. A0 is the LiteRT Micro baseline; B1.1 introduces the SALT custom compiler. Historical capture/configuration names remain unchanged.",
        "",
        "![Cumulative instruction counts](optimization-history.svg)",
        "",
        "Chart exports: [SVG](optimization-history.svg), [PNG](optimization-history.png), [PDF](optimization-history.pdf).",
        "",
        "| Stage | Change | Retired instructions | Removed vs previous stage | Reduction | Reduction from A0 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['stage']} | {row['title']} | {row['instructions']:,} | {row['instructions_removed']:,} | {row['reduction_pct']:.3f}% | {row['reduction_from_A0_pct']:.3f}% |"
        )
    lines.extend(
        [
            "",
            "## Affected operators",
            "",
            "Positive values are instructions removed from the immediate measured parent; negative values are increases. B1.6 includes caller scheduling and cannot isolate all scaling arithmetic.",
            "",
            "| Stage | Focus | Instructions removed in focus | Removed elsewhere | Loads/stores removed in focus |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in focus_rows:
        lines.append(
            f"| {row['stage']} | {row['focus']} | {row['focus_instructions_removed']:,} | {row['other_instructions_removed']:,} | {row['focus_memory_instructions_removed']:,} |"
        )
    lines.extend(
        [
            "",
            "## Storage tradeoffs",
            "",
            "| Stage | Executable bytes | Prepared constants/parameters bytes | Activation workspace bytes |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in footprint_rows:
        sizes = [
            f"{int(row[k]):,}" if row[k] is not None else "—"
            for k in (
                "executable_code",
                "planned_constants_and_parameters",
                "activation_scratch_workspace",
            )
        ]
        lines.append(f"| {row['stage']} | {' | '.join(sizes)} |")
    lines.extend(
        [
            "",
            "The chart uses seven bars. B1.4 is retained in the stage table; the B1.5 presentation delta combines B1.4 and B1.5. `presentation.csv` contains those grouped deltas. `stages.csv` always compares adjacent measured stages.",
            "",
            "B1.7 reproduces the accepted B1 full instruction mix, per-operator metrics and footprint exactly. The historical OC4 path and its 4.451% final-step reduction remain historical evidence; they are not deltas for this reordered sequence.",
            "",
            "`instruction-mix.csv` records loads, stores, integer ALU, multiply and branch counts plus MAC ratios. `operators.csv` and `nodes.csv` record inclusive family/node costs and adjacent-stage savings. `footprint.csv` records executable bytes, constants, read-only storage and workspace. `validation.json` identifies the immutable captures and acceptance checks.",
            "",
            "`functions.csv` retains exclusive function-body counts for generated stages. `scaling-helpers.csv` summarizes identifiable out-of-line fixed-point multiplier bodies. Selected inlining moves arithmetic into callers, so this helper-only count is not the total requantization cost or an estimate of the B1.6 benefit; use adjacent whole-model/node deltas for that comparison.",
            "",
            "A0 (historical B0) uses the original collector rather than a compiler capture ID; its frozen summary and raw-capture hashes are recorded in `validation.json`. Empty A0 prepared-data/workspace cells mean unavailable under the compiler's memory-plan accounting, not zero bytes.",
            "",
            "Counts are measured retirements; differences, ratios and artifact sizes are derived. Inclusive operator costs include requantization and callees; there is no claim that all arithmetic or all B1.6 savings can be isolated as requantization instructions. Memory opcodes do not measure cache misses or external traffic. Spike provides no hardware cycle speedup, CPI, area or Fmax evidence. A0 retains the frozen LiteRT flags and invocation boundary; B1.1–B1.7 use the same pinned compiler and generated-invocation boundary. Historical evidence paths/configurations retain B0 for LiteRT and A0 for static compilation.",
            "",
            "Every new stage passed native output, intermediate-array and sanitizer comparison against the pinned oracle (including the known rejected Softmax domain), ordinary Spike comparison of 1,000 output bytes, and two identical event/PC profiles on seed-1 input. Each stage directory contains its detailed summary and experiment receipt. Raw captures and complete source/build snapshots remain under ignored `build/`; rerun the sequence to regenerate them on a clean checkout.",
            "",
        ]
    )
    (OUTPUT / "README.md").write_text("\n".join(lines))
    print(f"Validated cumulative software report: {OUTPUT}")


if __name__ == "__main__":
    generate()
