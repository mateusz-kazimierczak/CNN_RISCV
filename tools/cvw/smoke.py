#!/usr/bin/env python3
"""Directed RTL checks for retirements, coherent output, and rejection gates."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    output = ROOT / "build/cvw/smoke"
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / ".deps/cvw"
    overlay = ROOT / "build/cvw/wally"
    env = dict(os.environ, WALLY=str(overlay), RISCV=str(ROOT / ".deps"), JOBS="8")
    env["PATH"] = os.pathsep.join(
        (str(ROOT / ".deps/verilator/bin"), str(overlay / "bin"), env["PATH"])
    )
    assembler = shutil.which("riscv64-unknown-elf-as")
    linker = shutil.which("riscv64-unknown-elf-ld")
    if not assembler or not linker:
        raise RuntimeError("install binutils-riscv64-unknown-elf first")
    elf = output / "smoke.elf"
    subprocess.run(
        [
            assembler,
            "-march=rv64imc",
            "-mabi=lp64",
            ROOT / "tools/cvw/smoke.S",
            "-o",
            output / "smoke.o",
        ],
        check=True,
    )
    subprocess.run(
        [
            linker,
            "-T",
            ROOT / "tflm/platform/rv64imc/link.ld",
            output / "smoke.o",
            "-o",
            elf,
        ],
        check=True,
    )
    subprocess.run(
        ["python3", source / "bin/elf2hex", elf, str(elf) + ".memfile"],
        env=env,
        check=True,
    )
    subprocess.run(
        ["bash", source / "bin/extractFunctionRadix.sh", elf, str(elf) + ".objdump"],
        env=env,
        check=True,
    )
    symbols = {}
    for line in subprocess.check_output(
        ["riscv64-unknown-elf-nm", elf], text=True
    ).splitlines():
        parts = line.split()
        if len(parts) == 3:
            symbols[parts[2]] = parts[0]
    record = {
        "schema_version": 1,
        "elf_sha256": hashlib.sha256(elf.read_bytes()).hexdigest(),
        "cases": {},
    }
    for case, count, limit, message in (
        ("correct", 19, 100000, "SUCCESS! All tests ran without failures."),
        ("wrong-count", 20, 100000, "Retirements disagree"),
        ("incomplete", 19, 1, "Project cycle limit reached; incomplete run"),
    ):
        metrics = output / (case + "-metrics.json")
        binary_output = output / (case + "-output.bin")
        for artifact in (metrics, binary_output):
            artifact.unlink(missing_ok=True)
        plusargs = " ".join(
            (
                f"+PROJECT_ENTRY={symbols['smoke_invoke']}",
                f"+PROJECT_RETURN={symbols['smoke_return']}",
                f"+PROJECT_OUTPUT_POINTER_PC={symbols['smoke_output_pointer_load']}",
                f"+PROJECT_EXPECTED={count}",
                f"+PROJECT_MAX_CYCLES={limit}",
                f"+PROJECT_METRICS={metrics}",
                f"+PROJECT_OUTPUT_FILE={binary_output}",
            )
        )
        command = [
            "python3",
            str(overlay / "bin/wsim"),
            "arch_project_rv64imc",
            str(elf),
            "--sim",
            "verilator",
            "--name",
            "smoke-" + case,
            "--args",
            plusargs,
        ]
        result = subprocess.run(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=900,
        )
        (output / (case + ".log")).write_text(result.stdout)
        if message not in result.stdout or (case == "correct") != (
            result.returncode == 0
        ):
            raise RuntimeError(f"unexpected smoke result: {case}; see {output}")
        details = {
            "status": "PASS",
            "process_exit": result.returncode,
            "expected_rejection": case != "correct",
        }
        if case == "correct":
            values = json.loads(metrics.read_text())
            expected = bytes((i ^ 0x5A) & 255 for i in range(1000))
            if values["instructions"] != "19" or binary_output.read_bytes() != expected:
                raise RuntimeError("smoke count or complete output mismatch")
            details.update(metrics=values, output_bytes_compared=1000)
        record["cases"][case] = details
    (output / "verification.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
