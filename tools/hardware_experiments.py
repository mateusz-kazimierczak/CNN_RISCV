"""Explicit hardware-era selections and validation of their immutable evidence."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from compiler.build_evidence import artifact_path, local_file
from compiler.kernel_plan import select_kernels
from compiler.quantization import PreparedGraph
from tools.profile_compiler import make_summary, verify_capture
from tools.profile_spike import Elf

MANIFEST = ROOT / "experiments/hardware.json"
CAPTURES = ROOT / "build/profiling/compiler"
RESULTS = ROOT / "results/profiling"


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def stages():
    spec = read(MANIFEST)
    require(spec["schema_version"] == 1, "unsupported hardware manifest")
    base = spec["base_options"]
    inline = read(ROOT / spec["software_manifest"])["inline_nodes"]
    resolved = {}
    for stage in spec["stages"]:
        require(stage["id"] not in resolved, "duplicate hardware stage")
        parent = stage["parent"]
        require(parent is None or parent in resolved, "parent must precede stage")
        options = {
            **(base if parent is None else resolved[parent]["options"]),
            **stage["options"],
        }
        resolved[stage["id"]] = {**stage, "options": options, "inline_nodes": inline}
    return list(resolved.values())


def flags(stage):
    result = []
    for key, value in stage["options"].items():
        if key.startswith("xqmac8_") and stage["config"] == "B1":
            continue
        if key.startswith("xrequant_") and stage["config"] in ("B1", "X1"):
            continue
        if key in ("xpostinc_depthwise", "depthwise_zero_point") and stage[
            "config"
        ] in ("B1", "X1", "X2"):
            continue
        if isinstance(value, bool):
            require(value, "false boolean option cannot be represented by this CLI")
            result.append("--" + key.replace("_", "-"))
        else:
            result.append("--" + key.replace("_", "-"))
            result.extend(map(str, value if isinstance(value, list) else [value]))
    return [*result, "--requantization-inline-nodes", *map(str, stage["inline_nodes"])]


def artifact(bundle, name):
    return artifact_path(
        bundle["directory"] / "build_evidence/manifest.json",
        bundle["verified"][1],
        name,
    )


def load_capture(path):
    saved = read(path)
    directory = CAPTURES / saved["capture_id"]
    verified = verify_capture(directory)
    summary = make_summary(directory, verified)
    # Historical summaries name the reporter version used at capture time.
    # Recompute all measurements/provenance; only that tool-version hash varies.
    comparable = lambda s: {
        k: v for k, v in s.items() if k != "report_generator_sha256"
    }
    require(
        comparable(summary) == comparable(saved),
        f"saved summary differs from frozen capture: {path}",
    )
    return {
        "directory": directory,
        "verified": verified,
        "summary": summary,
        "summary_path": Path(path),
    }


def validate_selection(stage, bundle):
    verified = bundle["verified"]
    graph = verified[2]
    prepared = PreparedGraph.from_json(
        artifact(bundle, "prepared_ir.json").read_text(), graph
    )
    options = dict(stage["options"])
    options["depthwise_kernels"] = tuple(options["depthwise_kernels"])
    options["requantization_overrides"] = {
        n: "inline-nonpositive" for n in stage["inline_nodes"]
    }
    expected = json.loads(
        select_kernels(graph, prepared, stage["config"], **options).to_json()
    )
    require(
        expected == read(artifact(bundle, "kernel_plan.json")),
        f"frozen plan differs from explicit selection: {stage['id']}",
    )


def custom_counts(summary):
    counts = Counter()
    for unit in summary["units"]:
        counts["xqmac8"] += unit.get("expected_xqmac8_instructions", 0)
        counts["xrequant"] += unit.get("expected_xrequant_instructions", 0)
        counts.update(unit.get("expected_xdwmac8_instructions", {}))
        for kind, n in unit.get("expected_xpostinc_instructions", {}).items():
            counts["xpostinc_" + kind] += n
    return dict(counts)


def loaded_elf(bundle):
    evidence = bundle["verified"][1]
    root = bundle["directory"] / "build_evidence"
    return Elf(local_file(root, evidence["files"][evidence["build"]["binary"]]["blob"]))


def same_loaded_program(a, b):
    x, y = loaded_elf(a), loaded_elf(b)
    return x.allocated() == y.allocated() and x.loads == y.loads


def validate_compatible(a, b):
    for key in ("model_sha256", "input", "boundary_policy"):
        require(a[key] == b[key], f"incompatible comparison: {key}")


def validate_transition(stage, before, after):
    a, b = before["summary"], after["summary"]
    validate_compatible(a, b)
    old = {tuple(u["nodes"]): u for u in a["units"]}
    new = {tuple(u["nodes"]): u for u in b["units"]}
    require(old.keys() == new.keys(), "execution-unit identities differ")
    changed = [
        key[0]
        for key in old
        if old[key]["metrics"]["instructions"] != new[key]["metrics"]["instructions"]
    ]
    if stage["id"] == "X2.2":
        require(
            sorted(changed) == [2, 8, 22, 26, 33, 37, 41, 56], "outlining scope differs"
        )
    if stage["id"] == "X2.3":
        require(
            sorted(changed) == [10, 17, 24, 28, 35, 39, 46, 50, 54],
            "wide ADD scope differs",
        )
    if stage["id"] in ("D1", "X4"):
        require(
            len(changed) == 16
            and all("depthwise" in old[(n,)]["implementation"] for n in changed),
            "depthwise ablation scope differs",
        )
    if stage["id"] == "X5":
        require(changed == [1], "packed stem must change only node 1")
    if stage["id"] in ("X2.2", "X2.3"):
        require(
            custom_counts(a) == custom_counts(b), "compiler tuning changed custom work"
        )
    if stage["id"] == "X4":
        for name in (
            "constants.cc",
            "constants.h",
            "prepared_ir.json",
            "memory_plan.json",
        ):
            require(
                artifact(before, name).read_bytes()
                == artifact(after, name).read_bytes(),
                f"D1/X4 data differs: {name}",
            )
    return changed
