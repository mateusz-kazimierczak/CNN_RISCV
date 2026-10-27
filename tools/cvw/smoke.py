#!/usr/bin/env python3
"""Directed RTL checks for retirements, coherent output, and rejection gates."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wally", type=Path, default=ROOT / "build/cvw/wally")
    parser.add_argument("--output", type=Path, default=ROOT / "build/cvw/smoke")
    parser.add_argument("--custom", choices=("X1", "X2", "X3", "X4"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / ".deps/cvw"
    overlay = args.wally.resolve()
    configuration = json.loads((overlay / "integration.json").read_text())["configuration"]
    env = dict(os.environ, WALLY=str(overlay), RISCV=str(ROOT / ".deps"), JOBS="8")
    env["PATH"] = os.pathsep.join(
        (str(ROOT / ".deps/verilator/bin"), str(overlay / "bin"), env["PATH"])
    )
    assembler = shutil.which("riscv64-unknown-elf-as")
    linker = shutil.which("riscv64-unknown-elf-ld")
    if not assembler or not linker:
        raise RuntimeError("install binutils-riscv64-unknown-elf first")
    elf = output / "smoke.elf"
    assembly = ROOT / "tools/cvw/smoke.S"
    expected_count = 19
    if args.custom:
        # Zero packed products preserve old rd=-1. A zero requant descriptor
        # produces zero, exercising cross-unit forwarding on the combined core.
        extra = "  li a1, 0\n  li a2, 0\n  li a3, -1\n  .insn r 0x0b, 0, 0, a3, a1, a2\n  li a4, -1\n  bne a3, a4, 6f\n"
        expected_count += 6
        if args.custom in ("X2", "X3", "X4"):
            extra += "  .insn r 0x0b, 1, 0, a3, a3, a1\n  bnez a3, 6f\n"
            expected_count += 2
        if args.custom in ("X3", "X4"):
            # Check the memory value and both updated bases. GNU la emits two
            # instructions under .option norelax: eleven extra retirements.
            extra += "  la a1, scratch\n  li a2, 7\n  .insn i 0x7b, 3, a2, a1, 8\n  addi a1, a1, -8\n  .insn i 0x2b, 3, a3, a1, 8\n  bne a2, a3, 6f\n  la a4, scratch\n  addi a4, a4, 8\n  bne a1, a4, 6f\n"
            expected_count += 11
        if args.custom == "X4":
            # Initialize all pairs, MAC one nonzero lane, then check every pair.
            for pair in range(4):
                extra += f"  .insn r 0x0b, 3, {pair}, x0, x0, x0\n"
            extra += "  li a1, 1\n  li a2, 7\n  .insn r 0x0b, 2, 0, x0, a1, a2\n  .insn r 0x0b, 4, 0, a3, x0, x0\n  li a4, 7\n  bne a3, a4, 6f\n"
            for pair in range(1, 4):
                extra += f"  .insn r 0x0b, 4, {pair}, a3, x0, x0\n  bnez a3, 6f\n"
            expected_count += 16
        assembly = output / "smoke.S"
        assembly.write_text((ROOT / "tools/cvw/smoke.S").read_text().replace("smoke_invoke:\n", "smoke_invoke:\n" + extra))
    subprocess.run(
        [
            assembler,
            "-march=rv64imc",
            "-mabi=lp64",
            assembly,
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
    cases = [
        ("correct", expected_count, 100000, "SUCCESS! All tests ran without failures."),
        ("wrong-count", expected_count + 1, 100000, "Retirements disagree"),
        ("incomplete", expected_count, 1, "Project cycle limit reached; incomplete run"),
    ]
    if args.custom:
        cases.append(("wrong-custom", expected_count, 100000, "Custom retirements disagree"))
    if args.custom in ("X3", "X4"):
        cases.append(("wrong-postinc", expected_count, 100000, "Custom retirements disagree"))
    if args.custom == "X4":
        cases.append(("wrong-bank", expected_count, 100000, "Bank retirements disagree"))
    for case, count, limit, message in cases:
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
        if args.custom:
            plusargs += f" +PROJECT_EXPECTED_QMAC={2 if case == 'wrong-custom' else 1}"
            plusargs += f" +PROJECT_EXPECTED_REQUANT={1 if args.custom in ('X2', 'X3', 'X4') else 0}"
            plusargs += f" +PROJECT_CUSTOM_METRICS={output / (case + '-custom.json')}"
            if args.custom in ("X3", "X4"):
                plusargs += f" +PROJECT_EXPECTED_POSTLOAD={2 if case == 'wrong-postinc' else 1} +PROJECT_EXPECTED_POSTSTORE=1"
            if args.custom == "X4":
                bank_names = ["xdwmac8", *(f"xdwset{i}" for i in range(4)), *(f"xdwget{i}" for i in range(4))]
                plusargs += f" +PROJECT_BANK +PROJECT_BANK_METRICS={output / (case + '-bank.json')}"
                for name in bank_names:
                    plusargs += f" +PROJECT_EXPECTED_{name}={2 if case == 'wrong-bank' and name == 'xdwget1' else 1}"
        command = [
            "python3",
            str(overlay / "bin/wsim"),
            configuration,
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
            if values["instructions"] != str(expected_count) or binary_output.read_bytes() != expected:
                raise RuntimeError("smoke count or complete output mismatch")
            details.update(metrics=values, output_bytes_compared=1000)
            if args.custom:
                custom = json.loads((output / (case + "-custom.json")).read_text())
                expected_custom = {"xqmac8": "1", "xrequant": "1" if args.custom in ("X2", "X3", "X4") else "0"}
                if args.custom in ("X3", "X4"):
                    expected_custom.update(xpostinc_load="1", xpostinc_store="1")
                if args.custom == "X4":
                    custom.update(json.loads((output / (case + "-bank.json")).read_text()))
                    expected_custom.update({name: "1" for name in bank_names})
                if custom != expected_custom:
                    raise RuntimeError("smoke custom retirement mismatch")
                details["custom_instructions"] = custom
        record["cases"][case] = details
    (output / "verification.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
