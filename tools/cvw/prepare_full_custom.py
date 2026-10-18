#!/usr/bin/env python3
"""Attach full-inference measurement to separate, verified custom RTL overlays."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.cvw.prepare import digest, save
from tools.cvw.prepare_xqmac8 import prepare as qmac
from tools.cvw.prepare_xrequant import prepare as requant
from tools.cvw.prepare_xpostinc import prepare as postinc


def prepare(configuration):
    name, generator = {
        "X1": ("xqmac8", qmac),
        "X2": ("xrequant", requant),
        "X3": ("xpostinc", postinc),
    }[configuration]
    output = ROOT / f"build/cvw/full-{name}"
    record = generator(ROOT / ".deps/cvw", output)
    monitor = output / "testbench/project_monitor.svh"
    save(monitor, monitor.read_bytes() + b"\n" + (ROOT / "tools/cvw/custom_monitor.svh").read_bytes())
    record["files_sha256"]["testbench/project_monitor.svh"] = digest(monitor)
    record.update(
        configuration=f"arch_project_{name}",
        config_sha256=record["configurations"][f"arch_project_{name}"]["sha256"],
        monitor_sha256=digest(monitor),
        testbench_sha256=digest(output / "testbench/testbench.sv"),
        measurement="same full-inference boundary as B0/B1; separate custom retirement counts",
    )
    sources = [
        "tools/cvw/project_monitor.svh", "tools/cvw/custom_monitor.svh",
        "tools/cvw/prepare_full_custom.py", f"tools/cvw/prepare_{name}.py",
        "rtl/cvw/xqmac8.patch", "rtl/cvw/xqmac8.sv",
    ]
    if configuration in ("X2", "X3"):
        sources += ["rtl/cvw/xrequant.patch", "rtl/cvw/xrequant.sv"]
    if configuration == "X3":
        sources += ["rtl/cvw/xpostinc.patch"]
    record["project_sources_sha256"] = {name: digest(ROOT / name) for name in sources}
    save(output / "integration.json", (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", choices=("X1", "X2", "X3"))
    print(prepare(parser.parse_args().configuration))
