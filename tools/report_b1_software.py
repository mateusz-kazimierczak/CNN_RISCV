"""Reconcile saved retirement captures into the accepted B1 report data.

Run from the repository root with the compiler requirements. Matplotlib is
needed only for --plot. This reads frozen snapshots, never regenerates kernels
and never estimates instruction counts from source or multiply opcodes.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compiler.build_evidence import canonical, digest
from profile_compiler import capture_directory, make_summary, verify_capture

HISTORY = (
    ("A0-static-metadata", "Static metadata A0"),
    ("B1-pointwise", "Scalar pointwise dot8"),
    ("B1-stem-unroll", "Stem loop unrolling"),
    ("B1-oc4", "Four output channels"),
    ("B1-depthwise", "Fixed depthwise filters"),
    ("B1-numerics", "Owned numerical helpers"),
    ("B1-project-kernels", "Remaining owned operators"),
    ("B1-standalone", "Reuse Softmax preflight"),
    ("B1-readable", "Readable source"),
    ("B1-requantization-selected", "Specialize requantization"),
    ("B1-spatial2-oc2", "Two pixels and two channels"),
)


def value(summary, section, name):
    return int(summary[section][name]["value"])


def load(directory):
    directory = capture_directory(directory)
    verified = verify_capture(directory)
    return make_summary(directory, verified), verified


def family(graph, node):
    if node.kind == "CONV_2D":
        shape = graph.tensors[node.input("weights")].shape
        return "Pointwise convolution" if shape[1:3] == (1, 1) else "Stem convolution"
    if node.kind == "DEPTHWISE_CONV_2D":
        size = graph.tensors[node.input("weights")].shape[1]
        return f"Depthwise {size}x{size}"
    return node.kind


def write_csv(path, rows):
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def generate(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    history, summaries = [], {}
    for checkpoint, title in HISTORY:
        path = ROOT / "results/profiling" / checkpoint / "summary.json"
        saved = json.loads(path.read_text())
        source = ROOT / "build/profiling/compiler" / saved["capture_id"]
        summary, _ = load(source)
        if summary["inference"] != saved["inference"]:
            raise ValueError(f"saved checkpoint metrics differ: {checkpoint}")
        summaries[checkpoint] = summary
        count = value(summary, "inference", "instructions")
        previous = int(history[-1]["instructions"]) if history else count
        history.append(
            {
                "checkpoint": checkpoint,
                "optimization": title,
                "instructions": str(count),
                "saved_vs_previous": str(previous - count),
                "memory_instructions": str(
                    value(summary, "inference", "memory_instructions")
                ),
                "executable_bytes": str(value(summary, "footprint", "executable_code")),
                "capture_id": summary["capture_id"],
                "elf_sha256": summary["elf_sha256"],
            }
        )

    a0, _ = load(args.a0_capture)
    final, final_verified = load(args.b1_capture)
    if a0["inference"] != summaries["A0-static-metadata"]["inference"]:
        raise ValueError("fresh A0 differs from the static-metadata checkpoint")
    if final["inference"] != summaries["B1-spatial2-oc2"]["inference"]:
        raise ValueError("fresh B1 differs from the accepted spatial checkpoint")
    for summary in [*summaries.values(), a0, final]:
        if (
            summary["input"] != final["input"]
            or summary["model_sha256"] != final["model_sha256"]
            or summary["boundary_policy"] != final["boundary_policy"]
        ):
            raise ValueError("model, input or invocation boundary mismatch")

    b0_path = ROOT / "results/profiling/B0/summary.json"
    b0 = json.loads(b0_path.read_text())
    contract = json.loads((ROOT / "tools/compiler/baseline.json").read_text())
    expected = contract["frozen_files"]["results/profiling/B0/summary.json"]
    if digest(b0_path) != (
        expected["sha256"] if isinstance(expected, dict) else expected
    ):
        raise ValueError("frozen B0 summary changed")
    if (
        b0["provenance"]["hashes"]["model"] != final["model_sha256"]
        or b0["provenance"]["input_seed"] != 1
    ):
        raise ValueError("B0 model/input mismatch")

    references = {
        "B0": b0,
        "A0": a0,
        "Initial B1": summaries["B1-pointwise"],
        "Previous B1": summaries["B1-requantization-selected"],
        "Accepted B1": final,
    }
    totals = {}
    for name, summary in references.items():
        totals[name] = {
            "instructions": (
                b0["inference"]["instructions"]
                if name == "B0"
                else value(summary, "inference", "instructions")
            ),
            "memory_instructions": (
                b0["inference"]["memory_instructions"]
                if name == "B0"
                else value(summary, "inference", "memory_instructions")
            ),
        }
    comparisons = []
    for name, total in totals.items():
        if name == "Accepted B1":
            continue
        after = totals["Accepted B1"]
        comparisons.append(
            {
                "reference": name,
                "before": str(total["instructions"]),
                "after": str(after["instructions"]),
                "instructions_saved": str(
                    total["instructions"] - after["instructions"]
                ),
                "reduction_fraction": {
                    "numerator": str(total["instructions"] - after["instructions"]),
                    "denominator": str(total["instructions"]),
                },
                "instruction_count_ratio": {
                    "numerator": str(total["instructions"]),
                    "denominator": str(after["instructions"]),
                },
                "memory_instructions_before": str(total["memory_instructions"]),
                "memory_instructions_after": str(after["memory_instructions"]),
                "memory_instructions_saved": str(
                    total["memory_instructions"] - after["memory_instructions"]
                ),
                "scope": "full_inference",
                "unit": "retired_instructions",
                "evidence": "derived_from_measured_counts",
            }
        )

    graph = final_verified[2]
    groups = {family(graph, n): [] for n in graph.nodes}
    for node in graph.nodes:
        groups[family(graph, node)].append(node.index)
    per_node, mix = {}, {}
    for name, summary in references.items():
        if name == "B0":
            per_node[name] = {n["index"]: n["instructions"] for n in summary["layers"]}
            mix[name] = summary["inference"]["mix"]
        else:
            if any(len(u["nodes"]) != 1 for u in summary["units"]):
                raise ValueError("this report requires one observed unit per node")
            per_node[name] = {
                u["nodes"][0]: int(u["metrics"]["instructions"]["value"])
                for u in summary["units"]
            }
            mix[name] = {
                key: int(metric["value"])
                for key, metric in summary["inference"]["mix"].items()
            }
        if set(per_node[name]) != set(range(64)):
            raise ValueError("logical node coverage differs")
    contributions = []
    for group, nodes in groups.items():
        contributions.append(
            {
                "operator_family": group,
                "nodes": len(nodes),
                **{
                    name: str(sum(per_node[name][n] for n in nodes))
                    for name in references
                },
            }
        )
    contributions.append(
        {
            "operator_family": "Invocation overhead",
            "nodes": 0,
            **{
                name: str(totals[name]["instructions"] - sum(per_node[name].values()))
                for name in references
            },
        }
    )
    for name in references:
        if sum(int(row[name]) for row in contributions) != totals[name]["instructions"]:
            raise ValueError("operator contributions do not conserve inference")
        if sum(mix[name].values()) != totals[name]["instructions"]:
            raise ValueError("instruction categories do not conserve inference")
    node_rows = [
        {
            "node": n,
            "operator_family": family(graph, graph.nodes[n]),
            **{name: str(per_node[name][n]) for name in references},
        }
        for n in range(64)
    ]
    mix_rows = [
        {
            "category": category,
            **{name: str(mix[name][category]) for name in references},
        }
        for category in mix["Accepted B1"]
    ]
    data = {
        "schema_version": 1,
        "scope": "full_inference",
        "input": final["input"],
        "model_sha256": final["model_sha256"],
        "history": history,
        "comparisons": comparisons,
        "operator_contributions": contributions,
        "instruction_mix": mix_rows,
        "fresh_a0": {"capture_id": a0["capture_id"], "elf_sha256": a0["elf_sha256"]},
        "accepted_b1": {
            "capture_id": final["capture_id"],
            "elf_sha256": final["elf_sha256"],
            "build_evidence_sha256": final["build_evidence_sha256"],
        },
        "metric_policy": "Counts measured from repeated captures; differences/ratios derived. No cycle or cache claims.",
        "checks": {
            "capture_integrity": True,
            "same_model_input_boundary": True,
            "operator_conservation": True,
            "category_conservation": True,
            "fresh_profiles_match_accepted_history": True,
            "frozen_B0_summary": True,
        },
    }
    (output / "comparison.json").write_text(canonical(data))
    for filename, rows in (
        ("checkpoint-history.csv", history),
        ("operator-contributions.csv", contributions),
        ("instruction-mix.csv", mix_rows),
        ("nodes.csv", node_rows),
    ):
        write_csv(output / filename, rows)

    if args.plot:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10.6, 6.7), layout="constrained")
        colors = ["#637587"] * (len(history) - 1) + ["#087f8c"]
        values = [int(row["instructions"]) / 1e9 for row in history]
        bars = ax.barh(range(len(history)), values, color=colors, height=0.68)
        ax.set_yticks(range(len(history)), [row["optimization"] for row in history])
        ax.invert_yaxis()
        for bar, count in zip(bars, values):
            ax.text(
                count + 0.025,
                bar.get_y() + bar.get_height() / 2,
                f"{count:.3f}",
                va="center",
                fontsize=9,
            )
        ax.set_xlim(0, 4.45)
        ax.set_xlabel("Retired instructions per inference (billions)")
        ax.set_title(
            "Software B1 optimization checkpoints", loc="left", weight="bold", pad=16
        )
        ax.xaxis.grid(True, alpha=0.18)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.tick_params(axis="y", length=0, pad=10)
        fig.savefig(output / "optimization-history.svg", metadata={"Date": None})
        fig.savefig(output / "optimization-history.png", dpi=170)
        plt.close(fig)
    print(f"Verified B1 report data: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a0-capture", type=Path, required=True)
    parser.add_argument("--b1-capture", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "results/profiling/B1-software"
    )
    parser.add_argument("--plot", action="store_true")
    generate(parser.parse_args())
