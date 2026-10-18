#!/usr/bin/env python3
"""Build and run the bank-enabled Wally SoC with authenticated ELF inputs."""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

WORK = ROOT / "build/cvw/xdwmac8"
OVERLAY = ROOT / "build/cvw/wally-xdwmac8"
PREFIX = str(ROOT / ".deps/xpack-riscv/bin/riscv-none-elf-")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log=None, live=False, **kwargs):
    command = list(map(str, command))
    if live:
        with Path(log).open("w") as stream:
            result = subprocess.run(
                command,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=kwargs.pop("timeout", 600),
                **kwargs,
            )
        text = Path(log).read_text()
        if result.returncode:
            raise RuntimeError(
                f"command failed ({result.returncode}); see {log}\n{text[-2000:]}"
            )
        return text
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=kwargs.pop("timeout", 600),
        **kwargs,
    )
    if log:
        Path(log).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command[:3]}; see {log}\n{(result.stdout + result.stderr)[-2000:]}"
        )
    return result.stdout


def build(configuration, jobs):
    output = WORK / configuration
    output.mkdir(parents=True, exist_ok=True)
    sources = [OVERLAY / "src/cvw.sv", Path(__file__).with_name("soc_tb.sv")]
    sources += sorted((OVERLAY / "src").glob("*/*.sv")) + sorted(
        (OVERLAY / "src").glob("*/*/*.sv")
    )
    verilator = shutil.which("verilator")
    if not verilator:
        raise RuntimeError("Verilator is required")
    command = [
        verilator,
        "--binary",
        "--timing",
        "--assert",
        "-j",
        str(jobs),
        "-Wno-fatal",
        "--top-module",
        "xdwmac8_soc_tb",
        "--Mdir",
        str(output),
        "-I" + str(OVERLAY / "config/shared"),
        "-I" + str(OVERLAY / "config" / configuration),
        *sources,
        ROOT / "tools/cvw/xqmac8/getenv.cc",
    ]
    env = dict(os.environ)
    host_compiler = shutil.which("c++")
    if sys.platform == "darwin":
        host_compiler = "/Library/Developer/CommandLineTools/usr/bin/clang++"
        sdk = Path("/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk")
        env["SDKROOT"] = (
            str(sdk) if sdk.exists() else run(["xcrun", "--show-sdk-path"]).strip()
        )
        command += ["-MAKEFLAGS", f"CXX={host_compiler} LINK={host_compiler}"]
    inputs = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    inputs.update(
        {
            str(Path(__file__).relative_to(ROOT)): digest(__file__),
            str((ROOT / "tools/cvw/xqmac8/getenv.cc").relative_to(ROOT)): digest(
                ROOT / "tools/cvw/xqmac8/getenv.cc"
            ),
            "integration.json": digest(OVERLAY / "integration.json"),
            "tools/xdwmac8/contract.py": digest(ROOT / "tools/xdwmac8/contract.py"),
        }
    )
    identity = {
        "inputs": inputs,
        "verilator": run([verilator, "--version"]).strip(),
        "verilator_sha256": digest(verilator),
        "command": list(map(str, command)),
        "compiler": run([host_compiler, "--version"]).splitlines()[0],
        "compiler_sha256": digest(host_compiler),
    }
    record = output / "build.json"
    binary = output / "Vxdwmac8_soc_tb"
    if record.exists() and binary.exists():
        old = json.loads(record.read_text())
        if old.get("identity") == identity and old["binary_sha256"] == digest(binary):
            return binary, old
    print(f"Building full SoC: {configuration}", flush=True)
    run(command, WORK / f"{configuration}-build.log", env=env, timeout=1200)
    if any(
        digest(ROOT / name) != value
        for name, value in inputs.items()
        if name != "integration.json"
    ):
        raise ValueError("RTL changed during compilation")
    value = {"identity": identity, "binary_sha256": digest(binary)}
    record.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    return binary, value


def compile_program(name, text, xlen=64):
    source, obj, elf = [WORK / (name + suffix) for suffix in (".S", ".o", ".elf")]
    source.write_text(text)
    run(
        [
            PREFIX + "as",
            f"-march=rv{xlen}imc_zicsr",
            "-mabi=" + ("lp64" if xlen == 64 else "ilp32"),
            source,
            "-o",
            obj,
        ]
    )
    run(
        [
            PREFIX + "ld",
            "-m",
            f"elf{xlen}lriscv",
            "-T",
            ROOT / "tflm/platform/rv64imc/link.ld",
            obj,
            "-o",
            elf,
        ]
    )
    return elf


def image(elf, xlen):
    data = elf.read_bytes()
    is64 = data[4] == 2
    phoff = struct.unpack_from("<Q" if is64 else "<I", data, 32 if is64 else 28)[0]
    stride, count = struct.unpack_from("<HH", data, 54 if is64 else 42)
    words = {}
    for index in range(count):
        parts = struct.unpack_from(
            "<IIQQQQQQ" if is64 else "<IIIIIIII", data, phoff + index * stride
        )
        if is64:
            kind, _, offset, address, _, size, _, _ = parts
        else:
            kind, offset, address, _, size, _, _, _ = parts
        if kind != 1:
            continue
        for i, byte in enumerate(data[offset : offset + size]):
            a = address + i - 0x80000000
            if not 0 <= a < 128 * 1024**2:
                raise ValueError("ELF outside modeled RAM")
            word, lane = divmod(a, xlen // 8)
            words[word] = words.get(word, 0) | (byte << (lane * 8))
    path = WORK / (elf.stem + f"-rv{xlen}.mem")
    path.write_text(
        "\n".join(f"@{a:x}\n{w:0{xlen // 4}x}" for a, w in sorted(words.items())) + "\n"
    )
    symbols = {
        p[2]: int(p[0], 16)
        for line in run([PREFIX + "nm", elf]).splitlines()
        if len(p := line.split()) == 3
    }
    return path, symbols


def execute(
    name,
    binary,
    elf,
    xlen=64,
    qmac=0,
    requant=0,
    postload=0,
    poststore=0,
    traps=0,
    bank=None,
    irq_pc=0,
    stall=0,
    timeout=600,
):
    bank = bank or {}
    mem, symbols = image(elf, xlen)
    command = [
        binary,
        "+IMAGE=" + str(mem),
        f"+TOHOST={symbols['tohost']:x}",
        f"+EXPECTED_CUSTOM={qmac + requant + postload + poststore + sum(bank.values())}",
        f"+EXPECTED_QMAC={qmac}",
        f"+EXPECTED_REQUANT={requant}",
        f"+EXPECTED_POSTLOAD={postload}",
        f"+EXPECTED_POSTSTORE={poststore}",
        f"+EXPECTED_TRAPS={traps}",
        f"+STALL_PERIOD={stall}",
        "+MAX_CYCLES=3000000000",
    ]
    command += [f"+EXPECTED_DWMAC={bank.get('xdwmac8',0)}",f"+IRQ_PC={irq_pc:x}"]
    command += [f"+EXPECTED_DWSET{i}={bank.get(f'xdwset{i}',0)}" for i in range(4)]
    command += [f"+EXPECTED_DWGET{i}={bank.get(f'xdwget{i}',0)}" for i in range(4)]
    text = run(command, WORK / (name + ".log"), timeout=timeout, live=True)
    match = re.search(r"XDWMAC8_RTL_PASS (.*)", text)
    if not match:
        raise ValueError(f"incomplete RTL test: {name}")
    metrics = {
        key: int(value)
        for key, value in re.findall(
            r"(\w+)=(\d+)",
            match[1]
            + " "
            + " ".join(
                re.findall(
                    r"(?:XPOSTINC_COVERAGE|XPOSTINC_HAZARDS|XREQUANT_COVERAGE|XDWMAC8_COVERAGE) (.*)",
                    text,
                )
            ),
        )
    }
    print(
        f"{name}: PASS ({metrics['custom']} custom, {metrics['traps']} traps)",
        flush=True,
    )
    return {
        "status": "PASS",
        "elf": str(elf.relative_to(ROOT)),
        "elf_sha256": digest(elf),
        "simulator_sha256": digest(binary),
        "command": list(map(str, command)),
        "metrics": metrics,
        "log_sha256": digest(WORK / (name + ".log")),
    }


