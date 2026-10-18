#!/usr/bin/env python3
"""Run a hash-bound checkpoint ELF on its verified Wally/Verilator overlay."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def loaded_bytes(path, address, size):
    data = path.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("expected a little-endian ELF64 executable")
    phoff = struct.unpack_from("<Q", data, 32)[0]
    stride, count = struct.unpack_from("<HH", data, 54)
    for index in range(count):
        kind, _, offset, virtual, _, filesz, _, _ = struct.unpack_from(
            "<IIQQQQQQ", data, phoff + index * stride
        )
        if kind == 1 and virtual <= address and address + size <= virtual + filesz:
            start = offset + address - virtual
            return data[start : start + size]
    raise ValueError("probe address is outside loaded ELF bytes")


def run(args):
    contract = json.loads(args.contract.read_text())
    workload = contract[args.configuration]
    elf = args.inputs / (args.configuration + ".elf")
    expected_output = args.inputs / "expected-output.bin"
    if digest(elf) != workload["elf_sha256"]:
        raise ValueError("ELF is not the preserved accepted workload")
    if "output_pointer_load_pc" in workload:
        encoding = bytes.fromhex(workload["output_pointer_load_encoding"])[::-1]
        if (
            loaded_bytes(
                elf, int(workload["output_pointer_load_pc"], 16), len(encoding)
            )
            != encoding
        ):
            raise ValueError(
                "output-pointer probe does not match the linked instruction"
            )
    if digest(expected_output) != contract["expected_output_sha256"]:
        raise ValueError("expected output identity changed")
    source = ROOT / ".deps/cvw"
    overlay = args.wally.resolve()
    integration = json.loads((overlay / "integration.json").read_text())
    revision = subprocess.check_output(
        ["git", "-C", source, "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != integration["wally_revision"] or subprocess.check_output(
        ["git", "-C", source, "diff", "HEAD", "--"]
    ):
        raise ValueError("pinned Wally sources changed")
    for name, key in (
        (f"config/{integration['configuration']}/config.vh", "config_sha256"),
        ("testbench/testbench.sv", "testbench_sha256"),
        ("testbench/project_monitor.svh", "monitor_sha256"),
    ):
        if digest(overlay / name) != integration[key]:
            raise ValueError(f"integration artifact changed: {name}")
    for name, expected in integration.get("files_sha256", {}).items():
        if digest(overlay / name) != expected:
            raise ValueError(f"integration source changed: {name}")
    if workload.get("extension") != integration.get("extension"):
        raise ValueError("workload and hardware extensions disagree")
    for name, expected in integration.get("project_sources_sha256", {}).items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"project hardware source changed: {name}")
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()
    env = dict(
        os.environ, WALLY=str(overlay), RISCV=str(ROOT / ".deps"), JOBS=str(args.jobs)
    )
    env["PATH"] = os.pathsep.join(
        (str(ROOT / ".deps/verilator/bin"), str(overlay / "bin"), env["PATH"])
    )
    for command in (
        ["python3", source / "bin/elf2hex", elf, str(elf) + ".memfile"],
        ["bash", source / "bin/extractFunctionRadix.sh", elf, str(elf) + ".objdump"],
    ):
        subprocess.run(command, env=env, check=True)
    plusargs = [
        f"+PROJECT_ENTRY={workload['entry']}",
        f"+PROJECT_RETURN={workload['return']}",
        f"+PROJECT_EXPECTED={workload['expected_instructions']}",
        f"+PROJECT_MAX_CYCLES={args.max_cycles}",
        f"+PROJECT_METRICS={output / 'metrics.json'}",
        f"+PROJECT_OUTPUT_FILE={output / 'output.bin'}",
    ]
    if "output_address" in workload:
        plusargs.append(f"+PROJECT_OUTPUT={workload['output_address']}")
    if "output_pointer_load_pc" in workload:
        plusargs.append(
            f"+PROJECT_OUTPUT_POINTER_PC={workload['output_pointer_load_pc']}"
        )
    if "custom_instructions" in workload:
        plusargs += [
            f"+PROJECT_EXPECTED_QMAC={workload['custom_instructions']['xqmac8']}",
            f"+PROJECT_EXPECTED_REQUANT={workload['custom_instructions']['xrequant']}",
            f"+PROJECT_CUSTOM_METRICS={output / 'custom-metrics.json'}",
        ]
        if "xpostinc_load" in workload["custom_instructions"]:
            plusargs += [
                f"+PROJECT_EXPECTED_POSTLOAD={workload['custom_instructions']['xpostinc_load']}",
                f"+PROJECT_EXPECTED_POSTSTORE={workload['custom_instructions']['xpostinc_store']}",
            ]
    command = [
        "python3",
        str(overlay / "bin/wsim"),
        integration["configuration"],
        str(elf),
        "--sim",
        "verilator",
        "--name",
        args.configuration,
        "--args",
        " ".join(plusargs),
    ]
    record = {
        "schema_version": 1,
        "status": "RUNNING",
        "configuration": args.configuration,
        "elf_sha256": digest(elf),
        "expected_output_sha256": digest(expected_output),
        "integration": integration,
        "contract_sha256": digest(args.contract),
        "workload": workload,
        "command": command,
        "verilator": subprocess.check_output(
            [str(ROOT / ".deps/verilator/bin/verilator"), "--version"], text=True
        ).strip(),
        "runner_pid": os.getpid(),
    }
    write_json(output / "run.json", record)
    started = time.monotonic()
    try:
        with (output / "simulation.log").open("w") as log:
            process = subprocess.Popen(
                command,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            record["launcher_pid"] = process.pid
            write_json(output / "run.json", record)
            try:
                code = process.wait(timeout=args.timeout)
            except BaseException:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait()
                raise
            if code:
                raise ValueError(f"simulation exited {code}; see simulation.log")
        text = (output / "simulation.log").read_text()
        if (
            "SUCCESS! All tests ran without failures." not in text
            or workload["pass_text"] not in text
        ):
            raise ValueError("missing application or testbench completion")
        metrics = json.loads((output / "metrics.json").read_text())
        if int(metrics["instructions"]) != int(workload["expected_instructions"]):
            raise ValueError("RTL and saved Spike retirements disagree")
        if "custom_instructions" in workload:
            custom = json.loads((output / "custom-metrics.json").read_text())
            if custom != workload["custom_instructions"]:
                raise ValueError("RTL and saved Spike custom retirements disagree")
            metrics["custom_instructions"] = custom
        actual = (output / "output.bin").read_bytes()
        if actual != expected_output.read_bytes():
            raise ValueError("complete output mismatch")
        record.update(
            status="PASS",
            metrics=metrics,
            output_bytes_compared=len(actual),
            output_sha256=digest(output / "output.bin"),
        )
        record["cpi"] = {
            "numerator": metrics["cycles"],
            "denominator": metrics["instructions"],
        }
    except Exception as error:
        record.update(status="FAIL", error=str(error))
        raise
    finally:
        record["wall_seconds"] = time.monotonic() - started
        simulator = (
            overlay
            / "sim/verilator/wkdir"
            / (integration["configuration"] + "_testbench")
            / "Vtestbench"
        )
        if simulator.exists():
            record["simulator_sha256"] = digest(simulator)
        write_json(output / "run.json", record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", choices=("B0", "B1", "X1", "X2", "X3"))
    parser.add_argument("--contract", type=Path, default=Path(__file__).with_name("workloads.json"))
    parser.add_argument("--wally", type=Path, default=ROOT / "build/cvw/wally")
    parser.add_argument("--inputs", type=Path, default=ROOT / "build/cvw/inputs")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=86400)
    parser.add_argument("--max-cycles", type=int, default=50000000000)
    run(parser.parse_args())
