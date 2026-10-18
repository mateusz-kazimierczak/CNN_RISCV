#!/usr/bin/env python3
"""Prepare the exact B0/B1 core configuration for NTHU standard-cell synthesis."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PIN = "712ee9719467e9e9987cebd55926ae8e01b08770"


def prepare(period):
    source = ROOT / ".deps/cvw"
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != PIN:
        raise ValueError(f"Wally revision must be {PIN}")
    subprocess.run([sys.executable, str(ROOT / "tools/cvw/prepare.py"), "--source", str(source),
                    "--output", str(ROOT / "build/cvw/wally")], check=True, stdout=subprocess.DEVNULL)
    config = ROOT / "build/cvw/wally/config/arch_project_rv64imc/config.vh"
    digest = hashlib.sha256(config.read_bytes()).hexdigest()
    evidence = json.loads((ROOT / "results/cvw/baseline/summary.json").read_text())
    for name in ("B0", "B1"):
        original = evidence["runs"][name]["integration"]
        if original["wally_revision"] != PIN or original["config_sha256"] != digest:
            raise ValueError(f"configuration differs from preserved {name} simulation")
    output = ROOT / "build/cvw/synth_baseline"
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config, output / "config.vh")
    # Reuse upstream's port-preserving wrapper to bind the cvw_t parameter.
    subprocess.run([sys.executable, str(source / "synthDC/scripts/wrapperGen.py"),
                    "wallypipelinedcore", str(output)], env={**os.environ, "WALLY": str(source)}, check=True)
    package = source / "src/cvw.sv"
    excluded = {"uncore", "rvvi"}
    rtl = [p for p in sorted((source / "src").rglob("*.sv"))
           if p != package and p.relative_to(source / "src").parts[0] not in excluded
           and p.name != "wallypipelinedsoc.sv"]
    relative = lambda p: p.relative_to(ROOT).as_posix()
    config = {
        "name": "cv-wally-b0-b1-baseline", "kind": "core",
        "scope": "wallypipelinedcore with 16KiB I-cache and 16KiB D-cache, USE_SRAM=0; external AHB boundary",
        "expected_wally_revision": PIN, "configuration_sha256": digest,
        "configuration_provenance": "Exact hash match to preserved B0 and B1 simulation integration records",
        "memory_implementation": "Standard-cell mapping of unchanged USE_SRAM=0 arrays; no SRAM macros or blackboxes",
        "top": "wallypipelinedcorewrapper",
        "sources": [relative(package)] + [relative(p) for p in rtl] + [relative(output / "wallypipelinedcorewrapper.sv")],
        "headers": [relative(output / "config.vh")] + [relative(p) for p in sorted((source / "config/shared").glob("*.vh"))],
        "include_dirs": [relative(output), relative(source / "config/shared")],
        "defines": [], "parameters": {},
        "clock": {"port": "clk", "period_ns": period, "uncertainty_ns": 0.1},
        "reset": "reset", "input_delay_ns": 1.0, "output_delay_ns": 1.0,
        "constraints": [], "allowed_blackboxes": []
    }
    path = ROOT / "synth/configs/cv_wally_b0.json"
    path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Prepared {len(config['sources'])} ordered sources; B0/B1 config SHA256={digest}")
    print(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period-ns", type=float, default=10.0,
                        help="optimization target, not measured frequency (default 10 ns)")
    args = parser.parse_args()
    if not 0 < args.period_ns < float("inf"):
        parser.error("period must be finite and positive")
    prepare(args.period_ns)
