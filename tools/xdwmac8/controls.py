#!/usr/bin/env python3
"""Rebuild prior selected schedules and compare every allocated byte/ELF segment."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.profile_spike import Elf
from tools.build_a0 import verify_build
from tools.xqmac8.runtime import digest


def control(item):
    config, reference = item
    folder = ROOT / "build/compiler" / (config + "-depthwise-control")
    log = ROOT / "build/xdwmac8" / (config + "-control.log")
    commands = [
        [
            sys.executable,
            "-m",
            "compiler",
            "generate",
            str(ROOT / "models/efficientnet-lite0-int8.tflite"),
            "--config",
            config,
            "--kernel-plan",
            str(ROOT / "build/compiler" / reference / "kernel_plan.json"),
            "--output-dir",
            str(folder),
        ],
        [
            sys.executable,
            "tools/build_a0.py",
            "build",
            "--kind",
            "rv64",
            "--generated-dir",
            str(folder),
        ],
    ]
    with log.open("w") as out:
        for command in commands:
            subprocess.run(
                command, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, check=True
            )
    a, b = (
        Elf(ROOT / "build/compiler" / reference / "rv64/a0.elf"),
        Elf(folder / "rv64/a0.elf"),
    )
    if a.allocated() != b.allocated() or a.loads != b.loads:
        raise ValueError(f"Legacy executable changed: {config}")
    record = verify_build(folder, "rv64")
    print(f"{config}: allocated sections and load segments identical", flush=True)
    return config, dict(
        status="PASS",
        reference=reference,
        allocated_sections_identical=True,
        load_segments_identical=True,
        control_elf_sha256=record["binary_sha256"],
        log_sha256=digest(log),
    )


def main():
    (ROOT / "build/xdwmac8").mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = dict(
            pool.map(
                control,
                [
                    ("B1", "B1-spatial2-oc2"),
                    ("X1", "X1-tile2x4"),
                    ("X2", "X2-optimized"),
                    ("X3", "X3-selected"),
                ],
            )
        )
    (ROOT / "build/xdwmac8/controls.json").write_text(
        json.dumps(dict(status="PASS", controls=rows), indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
