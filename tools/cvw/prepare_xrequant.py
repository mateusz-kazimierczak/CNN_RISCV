#!/usr/bin/env python3
"""Prepare a separate Xqmac8 + Xrequant RTL overlay without modifying pinned CV-Wally."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.cvw.prepare import OVERRIDES, WALLY_REVISION, link, save


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source, output):
    source, output = source.resolve(), output.resolve()
    revision = subprocess.check_output(
        ["git", "-C", source, "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != WALLY_REVISION or subprocess.check_output(
        ["git", "-C", source, "diff", "HEAD", "--"]
    ):
        raise ValueError("requires clean pinned Wally source")
    patches = [ROOT / "rtl/cvw/xqmac8.patch", ROOT / "rtl/cvw/xrequant.patch"]
    changed = sorted(
        {
            name
            for patch in patches
            for name in re.findall(r"^\+\+\+ b/(.+)$", patch.read_text(), re.MULTILINE)
        }
    )
    if set(changed) != {
        "src/cvw.sv",
        "src/wally/wallypipelinedcore.sv",
        "src/privileged/privileged.sv",
        "src/privileged/privpiperegs.sv",
        "src/ieu/controller.sv",
        "src/ieu/datapath.sv",
        "src/ieu/ieu.sv",
        "src/ieu/regfile.sv",
        "config/shared/parameter-defs.vh",
    }:
        raise ValueError("unexpected patch inventory")
    if output.exists():
        # Verify ownership before refreshing only the small copied RTL files.
        record = output / "integration.json"
        if (
            not record.exists()
            or json.loads(record.read_text()).get("extension") != "Xqmac8-Xrequant-v1"
        ):
            raise ValueError("refusing to replace an unrelated overlay")
        previous = json.loads(record.read_text())
        for name, expected in previous["files_sha256"].items():
            path = output / name
            if path.is_symlink() or digest(path) != expected:
                raise ValueError(
                    f"preserve modified overlay file before regenerating: {path}"
                )
        for name, expected in previous["configurations"].items():
            path = output / "config" / name / "config.vh"
            if path.is_symlink() or digest(path) != expected["sha256"]:
                raise ValueError(f"preserve modified overlay configuration: {path}")
    output.mkdir(parents=True, exist_ok=True)

    def mirror(directory):
        for child in (source / directory).iterdir():
            relative = child.relative_to(source)
            target = output / relative
            if str(relative) in changed:
                target.parent.mkdir(parents=True, exist_ok=True)
                save(target, child.read_bytes())
            elif any(p.startswith(str(relative) + "/") for p in changed):
                target.mkdir(parents=True, exist_ok=True)
                mirror(relative)
            else:
                link(child, target)

    mirror(Path("src"))
    mirror(Path("config/shared"))
    for name in (
        "bin",
        "addins",
        "testbench/common",
        "testbench/Makefile",
        "sim/verilator/Makefile",
        "sim/verilator/wrapper.c",
    ):
        link(source / name, output / name)
    # All patch targets are regular owned copies, never symlinks into .deps.
    for patch in patches:
        subprocess.run(
            ["patch", "-p1", "--batch", "-i", str(patch)],
            cwd=output,
            check=True,
            capture_output=True,
        )
    for name in ("xqmac8", "xrequant"):
        save(output / f"src/ieu/{name}.sv", (ROOT / f"rtl/cvw/{name}.sv").read_bytes())
    configurations = {}
    for name, xlen, qmac, requant in (
        ("arch_project_xrequant", 64, 1, 1),
        ("arch_project_xrequant_off", 64, 1, 0),
        ("arch_project_xrequant_only", 64, 0, 1),
        ("arch_project_xrequant_rv32", 32, 1, 1),
    ):
        config = (source / f"config/rv{xlen}i/config.vh").read_text()
        for key, value in OVERRIDES.items():
            pattern = rf"(localparam[^;\n]*\b{key}\s*=\s*)[^;]+;"
            config, count = re.subn(
                pattern, lambda m, value=value: m[1] + value + ";", config
            )
            if count != 1:
                raise ValueError(f"configuration field {key}: {count} matches")
        config += f"\n// Project extension enable, consumed by parameter-defs.vh.\n`define ARCH_PROJECT_XQMAC8_ENABLED 1'b{qmac}\n`define ARCH_PROJECT_XREQUANT_ENABLED 1'b{requant}\n"
        path = output / "config" / name / "config.vh"
        path.parent.mkdir(parents=True, exist_ok=True)
        save(path, config.encode())
        configurations[name] = {
            "xlen": xlen,
            "xqmac8": bool(qmac),
            "xrequant": bool(requant),
            "sha256": digest(path),
        }
    testbench = (source / "testbench/testbench.sv").read_text()
    save(
        output / "testbench/testbench.sv",
        testbench.replace(
            "\nendmodule\n", '\n`include "project_monitor.svh"\n\nendmodule\n'
        ).encode(),
    )
    monitor = ROOT / "tools/cvw/project_monitor.svh"
    save(output / "testbench/project_monitor.svh", monitor.read_bytes())
    owned = changed + [
        "src/ieu/xqmac8.sv",
        "src/ieu/xrequant.sv",
        "testbench/testbench.sv",
        "testbench/project_monitor.svh",
    ]
    record = {
        "schema_version": 1,
        "extension": "Xqmac8-Xrequant-v1",
        "rtl_modified": True,
        "wally_revision": revision,
        "patches_sha256": {str(p.relative_to(ROOT)): digest(p) for p in patches},
        "generator_sha256": digest(Path(__file__)),
        "configurations": configurations,
        "files_sha256": {name: digest(output / name) for name in owned},
        "implementation": "combinational E-stage units, forwarded descriptor validation, precise M-stage illegal trap",
        "instruction_matches": {"xqmac8": "0x0000000b", "xrequant": "0x0000100b"},
        "instruction_mask": "0xfe00707f",
    }
    save(
        output / "integration.json",
        (json.dumps(record, indent=2, sort_keys=True) + "\n").encode(),
    )
    print(output / "integration.json")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / ".deps/cvw")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "build/cvw/wally-xrequant"
    )
    args = parser.parse_args()
    prepare(args.source, args.output)
