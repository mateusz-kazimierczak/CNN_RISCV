#!/usr/bin/env python3
"""Validate full-model Spike evidence for the midterm without reading RTL files."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from compiler.build_evidence import canonical, digest
from tools.hardware_experiments import (
    MANIFEST as HARDWARE_MANIFEST,
    custom_counts,
    load_capture,
    read,
    require,
    same_loaded_program,
    stages as hardware_stages,
    validate_compatible,
    validate_selection,
    validate_transition,
)
from tools.profile_spike import CATEGORIES, report as baseline_report
from tools.run_software_experiments import MANIFEST, stages, verify_correctness

FROZEN_BASELINE = ROOT / "results/profiling/B0/summary.json"
OUTPUT = ROOT / "results/midterm"
GATES = {
    "repeat_histograms_identical": True,
    "per_pc_partition": True,
    "full_output_bytes_compared": 1000,
    "observed_execution_units": 64,
}


def load_baseline(path):
    path = Path(path).resolve()
    saved = read(path)
    contract = read(ROOT / "tools/compiler/baseline.json")
    if path == FROZEN_BASELINE:
        expected = contract["frozen_files"]["results/profiling/B0/summary.json"]
        require(
            digest(path) == (expected["sha256"] if isinstance(expected, dict) else expected),
            "frozen baseline summary changed",
        )
        kind = "retained_frozen_reference"
    else:
        configuration = saved["configuration"]
        require(
            re.fullmatch(r"[A-Za-z0-9_-]+", configuration),
            "invalid fresh baseline configuration",
        )
        raw = ROOT / "build/profiling" / configuration
        # Recompute from the new raw histograms, independently of the saved JSON.
        with tempfile.TemporaryDirectory(prefix="midterm-baseline-") as temp:
            baseline_report(raw, Path(temp))
            require(read(Path(temp) / "summary.json") == saved, "fresh baseline differs from raw capture")
        kind = "fresh_spike_measurement"
    provenance = saved["provenance"]
    require(provenance["hashes"]["model"] == contract["model_sha256"], "baseline model differs")
    require(provenance["input_seed"] == 1, "baseline input differs")
    require(provenance["output_fnv1a"] == contract["output"]["fnv1a"], "baseline output differs")
    require(provenance["repeat_histograms_identical"] is True, "baseline repeats differ")
    require(provenance["loadable_sections_identical"] is True, "baseline profile ELF differs")
    require(saved["inference"]["instructions"] == contract["inference_instructions"], "baseline count differs")
    require(sum(saved["inference"]["mix"].values()) == saved["inference"]["instructions"], "baseline mix differs")
    return saved, {"kind": kind, "summary": str(path.relative_to(ROOT)), "sha256": digest(path)}


def compiler_row(label, title, bundle):
    summary = bundle["summary"]
    require(summary["gates"] == GATES, "incomplete full-model capture gates")
    inference = summary["inference"]
    mix = {name: int(inference["mix"][name]["value"]) for name in CATEGORIES}
    count = int(inference["instructions"]["value"])
    require(sum(mix.values()) == count, "instruction mix does not conserve inference")
    custom = sum(custom_counts(summary).values())
    postinc = sum(int(v["value"]) for v in inference.get("postincrement", {}).values())
    require(custom == mix["custom"] + postinc, "custom utilization differs from classified mix")
    macs = int(inference["logical_macs"]["value"])
    return {
        "stage": label, "title": title, "instructions": count,
        **mix, "memory_instructions": mix["load"] + mix["store"],
        "logical_macs_per_instruction": macs / count,
        "memory_instructions_per_logical_mac": (mix["load"] + mix["store"]) / macs,
        "custom_encoding_instructions": custom, "custom_frequency": custom / count,
        "executable_code_bytes": summary["footprint"]["executable_code"]["value"],
        "capture_id": summary["capture_id"],
    }


def generate(baseline_path=FROZEN_BASELINE, output=OUTPUT):
    baseline, baseline_identity = load_baseline(baseline_path)
    inference = baseline["inference"]
    mix = {name: inference["mix"].get(name, 0) for name in CATEGORIES}
    rows = [{
        "stage": "A0", "title": "LiteRT Micro baseline", "instructions": inference["instructions"],
        **mix, "memory_instructions": mix["load"] + mix["store"],
        "logical_macs_per_instruction": inference["logical_macs"] / inference["instructions"],
        "memory_instructions_per_logical_mac": (mix["load"] + mix["store"]) / inference["logical_macs"],
        "custom_encoding_instructions": 0, "custom_frequency": 0,
        "executable_code_bytes": baseline["provenance"]["footprint"]["executable_code_bytes"],
        "capture_id": "",
    }]
    identities, previous = [], None
    for stage in stages():
        result = ROOT / "results/profiling" / stage["checkpoint"]
        receipt = read(result / "experiment.json")
        require(receipt["selection"] == {
            "manifest_sha256": digest(MANIFEST), "stage": stage,
            "parent_capture_id": previous["summary"]["capture_id"] if previous else None,
        }, "software selection or lineage differs")
        bundle = load_capture(result / "summary.json")
        require(receipt["capture_id"] == bundle["summary"]["capture_id"], "software receipt capture differs")
        correctness = verify_correctness(ROOT / "build/compiler" / stage["checkpoint"])
        if previous:
            validate_compatible(previous["summary"], bundle["summary"])
            require(read(bundle["directory"] / "parent-summary.json") == previous["summary"], "software parent differs")
            require((bundle["directory"] / "parent-identity.txt").read_text().strip() == digest(previous["directory"] / "manifest.json"), "software parent identity differs")
        row = compiler_row(stage["id"], stage["title"], bundle)
        require(row["custom_encoding_instructions"] == 0, "software stage uses custom instructions")
        if stage["present"]:
            rows.append(row)
        identities.append({"stage": stage["id"], "capture_id": row["capture_id"], "summary_sha256": digest(result / "summary.json"), "native_verification": correctness})
        previous = bundle
    require(previous["summary"]["model_sha256"] == baseline["provenance"]["hashes"]["model"], "software/baseline model differs")
    hardware = hardware_stages()
    index = read(ROOT / "results/profiling/hardware-progression/captures.json")
    require(index["complete"] and index["manifest_sha256"] == digest(HARDWARE_MANIFEST), "hardware capture index is incomplete or stale")
    require([r["stage"] for r in index["stages"]] == [s["id"] for s in hardware], "hardware capture inventory differs")
    bundles = {}
    for stage, record in zip(hardware, index["stages"], strict=True):
        path = ROOT / record["summary"]
        require(digest(path) == record["summary_sha256"], "indexed hardware summary changed")
        bundle = load_capture(path)
        require(bundle["summary"]["capture_id"] == record["capture_id"], "indexed hardware capture differs")
        validate_selection(stage, bundle)
        if stage["parent"]:
            validate_transition(stage, bundles[stage["parent"]], bundle)
        else:
            validate_compatible(previous["summary"], bundle["summary"])
            require(previous["summary"]["inference"] == bundle["summary"]["inference"], "accepted B1 instruction metrics differ")
            require(same_loaded_program(previous, bundle), "accepted B1 loaded program differs")
        row = compiler_row(stage.get("presentation", stage["id"]), stage.get("presentation_title", stage["title"]), bundle)
        if stage.get("presentation") and stage["id"] != "B1":
            rows.append(row)
        identities.append({"stage": stage["id"], "capture_id": row["capture_id"], "summary_sha256": digest(path)})
        bundles[stage["id"]] = bundle
    for i, row in enumerate(rows):
        before = rows[i - 1]["instructions"] if i else row["instructions"]
        row["instructions_removed"] = before - row["instructions"]
        row["reduction_pct"] = 100 * (before - row["instructions"]) / before
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "progression.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / "validation.json").write_text(canonical({
        "schema_version": 1, "scope": "midterm: full-model Spike ISA evaluation; no RTL or PPA inputs",
        "generator_sha256": digest(Path(__file__)), "software_manifest_sha256": digest(MANIFEST),
        "hardware_manifest_sha256": digest(HARDWARE_MANIFEST), "baseline": baseline_identity,
        "captures": identities, "progression_sha256": digest(output / "progression.csv"),
        "checks": {"capture_integrity": True, "selection_and_lineage": True, "complete_output_and_identical_repeats": True, "native_intermediate_sanitizer_checks": True, "same_loaded_B1_program": True},
    }))
    write_readme(rows, baseline_identity, output)
    print(f"Validated Spike-only midterm report: {output}")


def write_readme(rows, baseline_identity, output):
    baseline_kind = (
        "the frozen LiteRT Micro reference"
        if baseline_identity["kind"] == "retained_frozen_reference"
        else "a fresh full-model LiteRT Micro profile"
    )
    lines = [
        "# Midterm ISA evaluation",
        "",
        "Full EfficientNet-Lite0 inference is evaluated in Spike across cumulative software and custom-ISA checkpoints. The table reports retired instructions on the canonical seed-1 input. The [evaluation guide](../../docs/midterm-submission.md) links source, verification, benchmark commands, and measurement definitions.",
        "",
        f"This comparison uses {baseline_kind}, recorded in `{baseline_identity['summary']}`. `validation.json` identifies the baseline and each selected immutable capture.",
        "",
        "| Checkpoint | Change | Retired instructions | Reduction from preceding displayed checkpoint |",
        "|---|---|---:|---:|",
    ]
    lines += [
        f"| {r['stage']} | {r['title']} | {r['instructions']:,} | {r['reduction_pct']:.3f}% |"
        for r in rows
    ]
    lines += [
        "",
        "B1.4 stem unrolling is grouped into B1.5. X1/X2 include their compiler refinements; X4 includes D1 software correction; X5 introduces no new ISA. Percentages compare adjacent displayed checkpoints using unrounded counts.",
        "",
        "## Metrics and verification",
        "",
        "`progression.csv` records the instruction mix, load/store instructions per logical MAC, MACs per instruction, custom-instruction frequency, and executable code bytes. Post-increment instructions are included in load/store totals and in custom utilization, without being added twice to the instruction mix.",
        "",
        "Counts cover invocation entry through its returning instruction and exclude allocation, input generation, verification, and printing. Generated stages compare all 1,000 public output bytes, require identical event/PC profiles, and partition inference into 64 execution units plus invocation overhead. The baseline collector checks the reference output checksum. Native correctness evidence includes intermediate tensors and sanitizer checks.",
        "",
        "The deterministic input evaluates implementation equivalence rather than dataset classification accuracy. Retired instructions do not establish cycle speedup, cache misses, external bandwidth, or physical execution time. This ISA evaluation uses no RTL or synthesis inputs.",
        "",
        "## Reproduce",
        "",
        "After the [host setup](../../README.md#build-and-run), `gmake midterm-benchmark` evaluates the full software/custom-ISA sequence with a fresh LiteRT profile. `gmake midterm-report` revalidates retained compiler captures against the frozen LiteRT reference. The report is produced by [report_midterm.py](../../tools/report_midterm.py).",
        "",
        "Raw captures, ELFs, and native build evidence reside under ignored `build/` and are generated by the benchmark. Compact results are included in the repository. `validation.json` records source/manifest hashes, capture identities, and acceptance checks.",
        "",
        "## Supporting analysis",
        "",
        "- [Baseline bottlenecks](../profiling/B0/analysis.md)",
        "- [Software optimizations and storage tradeoffs](../../docs/B1-software-report.md)",
        "- [ISA comparisons and controls](../../docs/hardware-optimization-report.md)",
        "- [Dot-product microbenchmarks and pointwise operators](../profiling/X1-tile2x4-replay/README.md)",
        "- [Depthwise, ADD, and further operator measurements](../profiling/X2-optimized-replay/README.md)",
        "",
    ]
    (output / "README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=FROZEN_BASELINE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    generate(args.baseline, args.output)
