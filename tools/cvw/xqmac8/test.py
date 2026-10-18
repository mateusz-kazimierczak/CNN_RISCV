#!/usr/bin/env python3
"""Execute Xqmac8 oracle vectors and hazards on the real pinned Wally SoC."""

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
from tools.cvw.prepare_xqmac8 import prepare
from tools.xqmac8.test import assembly
from tools.xqmac8.vectors import MASK64, oracle, vectors

WORK = ROOT / "build/cvw/xqmac8"
OVERLAY = ROOT / "build/cvw/wally-xqmac8"
PREFIX = str(ROOT / ".deps/xpack-riscv/bin/riscv-none-elf-")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log=None, **kwargs):
    command = list(map(str, command))
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
        "xqmac8_soc_tb",
        "--Mdir",
        str(output),
        "-I" + str(OVERLAY / "config/shared"),
        "-I" + str(OVERLAY / "config" / configuration),
        *sources,
        Path(__file__).with_name("getenv.cc"),
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
            str(Path(__file__).with_name("getenv.cc").relative_to(ROOT)): digest(
                Path(__file__).with_name("getenv.cc")
            ),
            "integration.json": digest(OVERLAY / "integration.json"),
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
    binary = output / "Vxqmac8_soc_tb"
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


def execute(name, binary, elf, xlen=64, custom=0, traps=0, stall=0, timeout=600):
    mem, symbols = image(elf, xlen)
    command = [
        binary,
        "+IMAGE=" + str(mem),
        f"+TOHOST={symbols['tohost']:x}",
        f"+EXPECTED_CUSTOM={custom}",
        f"+EXPECTED_TRAPS={traps}",
        f"+STALL_PERIOD={stall}",
        "+MAX_CYCLES=3000000000",
    ]
    text = run(command, WORK / (name + ".log"), timeout=timeout)
    match = re.search(r"XQMAC8_RTL_PASS (.*)", text)
    if not match:
        raise ValueError(f"incomplete RTL test: {name}")
    metrics = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", match[1])}
    print(
        f"{name}: PASS ({metrics['custom']} custom, {metrics['traps']} traps)",
        flush=True,
    )
    return {
        "status": "PASS",
        "elf_sha256": digest(elf),
        "simulator_sha256": digest(binary),
        "command": list(map(str, command)),
        "metrics": metrics,
        "log_sha256": digest(WORK / (name + ".log")),
    }


def envelope(body, xlen=64):
    store = "sd" if xlen == 64 else "sw"
    return f""".option norvc
.option norelax
.section .text.init
.globl _start
_start:
{body}
pass:
  li a0, 1
  j exit
fail:
  li a0, 3
exit:
  la a1, tohost
  {store} a0, 0(a1)
1: j 1b
.section .tohost,"aw",@progbits
.balign 64
.globl tohost, fromhost
tohost: .dword 0
fromhost: .dword 0
"""


def hazards():
    regs = {0: 0, 5: 123, 6: 0x010203040506077F, 7: 0x807F01FF02030405}
    lines = [f"li x{r}, 0x{x:x}" for r, x in regs.items() if r]
    lines += [
        "li s10, 17",
        "li s11, 3",
        "li s8, 0xdeadbeef80000001",
        "csrw mscratch, s8",
        "la s6, load_value",
    ]
    total = 0

    def qmac(rd=5, rs1=6, rs2=7, check=True):
        nonlocal total
        value = oracle(regs[rd], regs[rs1], regs[rs2]) if rd else 0
        lines.append(f".insn r 0x0b, 0, 0, x{rd}, x{rs1}, x{rs2}")
        regs[rd] = value
        total += 1
        if check:
            lines.extend([f"li s5, 0x{value:x}", f"bne x{rd}, s5, fail"])

    producers = [
        ("addi x{r}, x{r}, 1", lambda r: (regs[r] + 1) & MASK64),
        ("add x{r}, s10, s11", lambda r: 20),
        ("mul x{r}, s10, s11", lambda r: 51),
        ("div x{r}, s10, s11", lambda r: 5),
        ("ld x{r}, 0(s6)", lambda r: 0xFEEDCAFE7FFFFFFF),
        ("csrr x{r}, mscratch", lambda r: 0xDEADBEEF80000001),
    ]
    # Each producer is immediately followed by a consumer dependent solely on
    # old rd. These make missing third-source stalls architecturally observable.
    for instruction, value in producers:
        lines.append(instruction.format(r=5))
        regs[5] = value(5)
        qmac()
    # Back-to-back dependency chain also tests priority over the older W result.
    for _ in range(64):
        qmac(check=False)
    lines.extend([f"li s5, 0x{regs[5]:x}", "bne t0, s5, fail"])
    rng = random.Random(0x57414C4C59)
    for _ in range(1000):
        r = rng.choice((5, 6, 7))
        instruction, value = rng.choice(producers)
        new = value(r)
        lines.append(instruction.format(r=r))
        regs[r] = new
        qmac(
            rng.choice((0, 5, 6, 7)), rng.choice((0, 5, 6, 7)), rng.choice((0, 5, 6, 7))
        )
    # Taken branches and jumps must kill younger custom operations. Check old
    # rd after each redirect, with no matching custom retirement added.
    for i in range(32):
        lines += [
            f"beq zero, zero, branch{i}",
            ".insn r 0x0b, 0, 0, t0, t1, t2",
            f"branch{i}:",
            f"li s5, 0x{regs[5]:x}",
            "bne t0, s5, fail",
        ]
    lines += [
        "j pass",
        ".section .rodata",
        ".balign 8",
        "load_value: .dword 0xfeedcafe7fffffff",
        ".section .text.init",
    ]
    return envelope("\n".join(lines)), total


def illegal(words, xlen=64):
    lines = ["la a0, handler", "csrw mtvec, a0", "li t0, 42"]
    for i, word in enumerate(words):
        lines += [
            f"la s0, illegal{i}",
            f"li s1, 0x{word:08x}",
            f"illegal{i}:",
            f".word 0x{word:08x}",
            ".word 0x0073028b",
        ]  # legal Xqmac8 on a flushed trap path
    lines += [
        "j pass",
        ".balign 4",
        "handler:",
        "csrr t3, mcause",
        "li t4, 2",
        "bne t3, t4, fail",
        "csrr t3, mepc",
        "bne t3, s0, fail",
        "csrr t3, mtval",
        "bne t3, s1, fail",
        "li t4, 42",
        "bne t0, t4, fail",
        "addi t3, s0, 8",
        "csrw mepc, t3",
        "mret",
    ]
    return envelope("\n".join(lines), xlen)


def compatibility(xlen, enabled=False):
    misa = f"csrr t3, misa\nsrli t3, t3, 23\nandi t3, t3, 1\nli t4, {int(enabled and xlen == 64)}\nbne t3, t4, fail\n"
    return envelope(
        misa
        + """li t0, 17
li t1, -3
mul t2, t0, t1
li t3, -51
bne t2, t3, fail
add zero, t2, t3
bne zero, zero, fail
.option rvc
c.addi t0, 1
c.addi t0, -1
.option norvc
li t3, 17
bne t0, t3, fail
j pass""",
        xlen,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--kernel-elf", type=Path)
    parser.add_argument("--kernel-custom", type=int)
    parser.add_argument(
        "--compiler-replay", type=Path, help="Verified X1 compiler replay latest.json"
    )
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    integration = prepare(ROOT / ".deps/cvw", OVERLAY)
    built = {
        key: build(key, args.jobs)
        for key in (
            "arch_project_xqmac8",
            "arch_project_xqmac8_off",
            "arch_project_xqmac8_rv32",
        )
    }
    enabled = built["arch_project_xqmac8"][0]
    cases = vectors()
    exported = WORK / "vectors.json"
    exported.write_text(
        json.dumps(
            {"contract_version": 1, "seed": "0x514d414338", "cases": cases}, indent=2
        )
        + "\n"
    )
    results = {}
    elf = compile_program("vectors", assembly(cases))
    for stall in (0, 31):
        name = "vectors" + ("-stalled" if stall else "")
        results[name] = execute(name, enabled, elf, custom=len(cases), stall=stall)
    text, count = hazards()
    elf = compile_program("hazards", text)
    for stall in (0, 31):
        name = "hazards" + ("-stalled" if stall else "")
        results[name] = execute(name, enabled, elf, custom=count, stall=stall)
        for gate in (
            "forward_m",
            "forward_w",
            "oldrd_load",
            "oldrd_mdu",
            "oldrd_csr",
            "flushes",
        ):
            if results[name]["metrics"][gate] == 0:
                raise ValueError(f"hazard coverage missing: {name}/{gate}")
    words = [
        (f7 << 25) | (7 << 20) | (6 << 15) | (f3 << 12) | (5 << 7) | 0x0B
        for f7 in range(128)
        for f3 in range(8)
        if (f7, f3) != (0, 0)
    ]
    words += [0x007302AB, 0x007302DB, 0x007302FB]
    elf = compile_program("invalid-encodings", illegal(words))
    results["invalid-encodings"] = execute(
        "invalid-encodings", enabled, elf, traps=len(words)
    )
    for config, xlen in (
        ("arch_project_xqmac8_off", 64),
        ("arch_project_xqmac8_rv32", 32),
    ):
        elf = compile_program(config + "-traps", illegal([0x0073028B], xlen), xlen)
        results[config + "-traps"] = execute(
            config + "-traps", built[config][0], elf, xlen, traps=1
        )
    for config, (binary, _) in built.items():
        xlen = 32 if config.endswith("rv32") else 64
        elf = compile_program(
            config + "-base", compatibility(xlen, config == "arch_project_xqmac8"), xlen
        )
        results[config + "-base"] = execute(config + "-base", binary, elf, xlen)
    if args.kernel_elf:
        if args.kernel_custom is None:
            parser.error("--kernel-custom is required with --kernel-elf")
        results["compiler-kernel-replay"] = execute(
            "compiler-kernel-replay",
            enabled,
            args.kernel_elf.resolve(),
            custom=args.kernel_custom,
            timeout=1200,
        )
    compiler_replay = None
    if args.compiler_replay:
        from tools.investigation.replay import verify_replay

        directory, manifest, workload, rows = verify_replay(args.compiler_replay)
        if workload["configuration"] != "X1":
            raise ValueError(
                "Xqmac8 hardware requires an X1 replay (Xrequant RTL is not enabled)"
            )
        count_custom = sum(
            int(row["invocation"]["mix"]["custom"]["value"]) for row in rows
        )
        kernel = (
            directory
            / json.loads((directory / "rv64/build.json").read_text())["binary"]
        )
        results["compiler-kernel-replay"] = execute(
            "compiler-kernel-replay", enabled, kernel, custom=count_custom, timeout=1200
        )
        text = (WORK / "compiler-kernel-replay.log").read_text()
        compared = [
            json.loads(line)
            for line in text.splitlines()
            if line.startswith('{"fixture":')
        ]
        if len(compared) != len(rows) or "compiler replay: PASS" not in text:
            raise ValueError("incomplete compiler replay output")
        for index, (actual, fixture) in enumerate(zip(compared, workload["fixtures"])):
            if (
                actual["fixture"] != index
                or not actual["guards"]
                or actual["first_difference"] is not None
                or actual["bytes_compared"] != fixture["output"]["bytes"]
                or actual["status"] != fixture["expected_status"]
            ):
                raise ValueError(f"compiler replay tensor mismatch: {index}")
        compiler_replay = {
            "artifact_id": directory.name,
            "fixtures": len(rows),
            "nodes": workload["nodes"],
            "cases": workload["cases"],
            "complete_output_bytes_compared": sum(
                x["bytes_compared"] for x in compared
            ),
            "custom_instructions": count_custom,
            "elf_sha256": digest(kernel),
        }
    for name, expected in integration["files_sha256"].items():
        if digest(OVERLAY / name) != expected:
            raise ValueError(f"overlay changed during tests: {name}")
    if subprocess.check_output(["git", "-C", ROOT / ".deps/cvw", "diff", "HEAD", "--"]):
        raise ValueError("pinned Wally source changed during tests")
    record = {
        "schema_version": 1,
        "status": "PASS",
        "integration": integration,
        "vectors": len(cases),
        "random_vectors": 10000,
        "vectors_sha256": digest(exported),
        "hazard_custom_operations": count,
        "illegal_encodings": len(words),
        "builds": {k: v[1] for k, v in built.items()},
        "cases": results,
        "compiler_replay": compiler_replay,
        "scope": "functional RTL on actual Wally SoC with caches; no synthesized frequency or area claim",
    }
    path = ROOT / "results/cvw/xqmac8/verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
    print(path)


if __name__ == "__main__":
    main()
