#!/usr/bin/env python3
"""Make an isolated Wally simulation overlay; never edit the pinned checkout."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

WALLY_REVISION = "712ee9719467e9e9987cebd55926ae8e01b08770"
CONFIGURATION = "arch_project_rv64imc"
OVERRIDES = {
    "M_SUPPORTED": "1",
    "ZMMUL_SUPPORTED": "1",
    "ZCA_SUPPORTED": "1",
    "ZICSR_SUPPORTED": "1",
    "ZIFENCEI_SUPPORTED": "1",
    "ZICNTR_SUPPORTED": "1",
    "ZIHPM_SUPPORTED": "1",
    "COUNTERS": "12'd32",
    "BUS_SUPPORTED": "1",
    "ICACHE_SUPPORTED": "1",
    "DCACHE_SUPPORTED": "1",
    "IROM_SUPPORTED": "0",
    "DTIM_SUPPORTED": "0",
    "UNCORE_RAM_SUPPORTED": "1",
    # Upstream procedural boot-mode branches reference the ROM hierarchy even
    # when those modes are not selected. Reset still enters RAM at 0x80000000.
    "BOOTROM_SUPPORTED": "1",
    "BPRED_SUPPORTED": "1",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def link(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        if destination.resolve() == source.resolve():
            return
        raise ValueError(f"unexpected existing link: {destination}")
    if destination.exists():
        raise ValueError(f"refusing to replace {destination}")
    destination.symlink_to(source.resolve(), target_is_directory=source.is_dir())


def prepare(source, output):
    source, output = source.resolve(), output.resolve()
    revision = subprocess.check_output(
        ["git", "-C", source, "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != WALLY_REVISION:
        raise ValueError(f"expected Wally {WALLY_REVISION}, found {revision}")
    if subprocess.check_output(["git", "-C", source, "diff", "HEAD", "--"]):
        raise ValueError("pinned Wally checkout has modified tracked files")
    output.mkdir(parents=True, exist_ok=True)
    for directory in ("src", "bin", "addins"):
        link(source / directory, output / directory)
    link(source / "config/shared", output / "config/shared")
    link(source / "testbench/common", output / "testbench/common")
    link(source / "testbench/Makefile", output / "testbench/Makefile")
    link(source / "sim/verilator/Makefile", output / "sim/verilator/Makefile")
    link(source / "sim/verilator/wrapper.c", output / "sim/verilator/wrapper.c")
    config = (source / "config/rv64i/config.vh").read_text()
    for name, value in OVERRIDES.items():
        pattern = rf"(localparam[^;\n]*\b{re.escape(name)}\s*=\s*)[^;]+;"
        config, count = re.subn(pattern, lambda m: m[1] + value + ";", config)
        if count != 1:
            raise ValueError(f"configuration field {name}: {count} matches")
    config_path = output / "config" / CONFIGURATION / "config.vh"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    save(config_path, config.encode())
    testbench = (source / "testbench/testbench.sv").read_text()
    marker = "\nendmodule\n"
    if testbench.count(marker) != 1:
        raise ValueError("unexpected upstream testbench module layout")
    testbench = testbench.replace(marker, '\n`include "project_monitor.svh"\n' + marker)
    save(output / "testbench/testbench.sv", testbench.encode())
    monitor = Path(__file__).with_name("project_monitor.svh")
    save(output / "testbench/project_monitor.svh", monitor.read_bytes())
    record = {
        "schema_version": 1,
        "wally_revision": revision,
        "configuration": CONFIGURATION,
        "base_configuration": "rv64i",
        "overrides": OVERRIDES,
        "config_sha256": digest(config_path),
        "testbench_sha256": digest(output / "testbench/testbench.sv"),
        "monitor_sha256": digest(monitor),
        "rtl_modified": False,
        "memory": "128 MiB modeled uncore RAM at 0x80000000; not a physical RAM capacity claim",
        "caches": "16 KiB each, 4 ways, 64-byte lines; upstream RV64I defaults",
        "clock": "testbench period only; no synthesized timing claim",
    }
    (output / "integration.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.output)
