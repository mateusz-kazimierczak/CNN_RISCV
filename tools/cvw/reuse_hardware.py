#!/usr/bin/env python3
"""Bind a software-only checkpoint to the unchanged, preflight-verified X4 core."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reuse(source, label, output):
    source = source.resolve()
    overlay = source / "build/cvw/full-xdwmac8"
    integration_path = overlay / "integration.json"
    integration = json.loads(integration_path.read_text())
    run = json.loads((source / f"build/cvw/runs/X4-{label}/run.json").read_text())
    if integration != run["integration"] or integration["extension"] != "Xqmac8-Xrequant-Xpostinc-Xdwmac8-v1":
        raise ValueError("hardware integration no longer matches the X4 run")
    if run["status"] not in ("RUNNING", "PASS"):
        raise ValueError("X4 hardware has no active or successful full-model run")
    if (ROOT / "build/cvw/full-xdwmac8").resolve() != overlay.resolve():
        raise ValueError("software checkpoint must use the original X4 overlay")
    fixture = source / f"build/cvw/runs/X4-{label}-smoke"
    path = fixture / "verification.json"
    verification = json.loads(path.read_text())
    if set(verification["cases"]) != {"correct", "incomplete", "wrong-count", "wrong-custom", "wrong-postinc", "wrong-bank"} or any(v["status"] != "PASS" for v in verification["cases"].values()):
        raise ValueError("missing X4 preflight gates")
    if digest(fixture / "smoke.elf") != verification["elf_sha256"]:
        raise ValueError("preflight executable changed")
    correct = verification["cases"]["correct"]
    if correct["metrics"]["instructions"] != "54" or correct["output_bytes_compared"] != 1000:
        raise ValueError("incomplete X4 preflight evidence")
    for name, expected in integration["files_sha256"].items():
        if digest(overlay / name) != expected:
            raise ValueError(f"hardware source changed: {name}")
    binary = overlay / "sim/verilator/wkdir" / (integration["configuration"] + "_testbench") / "Vtestbench"
    identity = digest(binary)
    if run.get("simulator_sha256", identity) != identity:
        raise ValueError("X4 simulator changed after capture")
    verification["hardware_reuse"] = {
        "source_project": str(source), "source_run_label": label,
        "simulator_sha256": identity, "integration_sha256": digest(integration_path),
        "source_verification_sha256": digest(path),
        "policy": "Reuse the existing X4 fixture results and exact simulator; no new hardware build or fixture execution.",
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "verification.json").write_text(json.dumps(verification, indent=2, sort_keys=True) + "\n")
    print(identity)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT.parent / "arch_project-xdwmac8")
    parser.add_argument("--source-run-label", default="dwmac-20261018")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reuse(args.source, args.source_run_label, args.output)
