#!/usr/bin/env python3
"""Execute both project instructions on the real pinned Wally SoC."""

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
from tools.cvw.prepare_xrequant import prepare
from tools.cvw.xqmac8 import test as qmac_tests
from tools.xqmac8.test import assembly as qmac_assembly
from tools.xqmac8.vectors import oracle as qmac_oracle
from tools.xqmac8.vectors import vectors as qmac_vectors
from tools.xrequant.contract import oracle, pack
from tools.xrequant.test import assembly, vectors

WORK = ROOT / "build/cvw/xrequant"
OVERLAY = ROOT / "build/cvw/wally-xrequant"
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
        "xrequant_soc_tb",
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
            **{
                str(p.relative_to(ROOT)): digest(p)
                for p in (
                    ROOT / "tools/cvw/xqmac8/test.py",
                    ROOT / "tools/xqmac8/test.py",
                    ROOT / "tools/xqmac8/vectors.py",
                    ROOT / "tools/xrequant/test.py",
                    ROOT / "tools/xrequant/contract.py",
                )
            },
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
    binary = output / "Vxrequant_soc_tb"
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
    name, binary, elf, xlen=64, qmac=0, requant=0, traps=0, stall=0, timeout=600
):
    mem, symbols = image(elf, xlen)
    command = [
        binary,
        "+IMAGE=" + str(mem),
        f"+TOHOST={symbols['tohost']:x}",
        f"+EXPECTED_CUSTOM={qmac + requant}",
        f"+EXPECTED_QMAC={qmac}",
        f"+EXPECTED_REQUANT={requant}",
        f"+EXPECTED_TRAPS={traps}",
        f"+STALL_PERIOD={stall}",
        "+MAX_CYCLES=3000000000",
    ]
    text = run(command, WORK / (name + ".log"), timeout=timeout)
    match = re.search(r"XREQUANT_RTL_PASS (.*)", text)
    if not match:
        raise ValueError(f"incomplete RTL test: {name}")
    metrics = {
        key: int(value)
        for key, value in re.findall(
            r"(\w+)=(\d+)",
            match[1] + " " + re.search(r"XREQUANT_COVERAGE (.*)", text)[1],
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
    descriptor = pack(0x60000000, -2, scale_only=True)
    regs = {0: 0, 5: 42, 6: 0xDEADBEEF80000001, 7: descriptor}
    lines = [f"li x{r}, 0x{v:x}" for r, v in regs.items() if r]
    lines += [
        "la s6, hazard_values",
        "li s10, 17",
        "li s11, 3",
        f"li s8, 0x{descriptor:x}",
        "csrw mscratch, s8",
    ]
    counts = {"qmac": 0, "requant": 0}

    def emit(kind, rd, a, b, check=True):
        value = (
            (
                oracle(regs[a], regs[b])
                if kind == "requant"
                else qmac_oracle(regs[rd], regs[a], regs[b])
            )
            if rd
            else 0
        )
        lines.append(f".insn r 0x0b,{int(kind == 'requant')},0,x{rd},x{a},x{b}")
        regs[rd] = value
        counts[kind] += 1
        if check:
            lines.extend([f"li s5, 0x{value:x}", f"bne x{rd}, s5, fail"])

    # Exercise both explicit sources with the real load/MDU/CSR interlocks.
    for r in (6, 7):
        for producer in ("addi", "add", "load", "mul", "div", "csr"):
            value = descriptor if r == 7 else 0xDEADBEEF80000001
            lines += [f"li s8, 0x{value:x}", "li s9, 1"]
            if producer == "load":
                lines += [f"ld x{r}, {8 if r == 7 else 0}(s6)"]
            elif producer == "csr":
                lines += ["csrw mscratch, s8", f"csrr x{r}, mscratch"]
            elif producer == "addi":
                lines += [f"addi x{r}, s8, 0"]
            elif producer == "add":
                lines += [f"add x{r}, s8, zero"]
            elif producer == "mul":
                lines += [f"mul x{r}, s8, s9"]
            else:
                lines += [f"divu x{r}, s8, s9"]
            regs[r] = value
            emit("requant", 5, 6, 7)
    # Newest M value must win over an older matching W producer. Two nops
    # separately force a true W forwarding case for each explicit source.
    for r in (6, 7):
        value = descriptor if r == 7 else 0x7FFFFFFF
        lines += [
            f"li s8, 0x{value:x}",
            f"addi x{r}, s8, 0",
            "nop",
            f"addi x{r}, s8, 0",
        ]
        regs[r] = value
        emit("requant", 5, 6, 7)
        lines += [f"addi x{r}, s8, 0", "nop"]
        emit("requant", 5, 6, 7)
    for _ in range(64):
        emit("requant", 5, 5, 7, check=False)
    lines += [f"li s5, 0x{regs[5]:x}", "bne t0, s5, fail"]
    # Alternate instructions with no checks in between: req -> implicit old rd,
    # and qmac -> req accumulator exercise cross-unit forwarding.
    for _ in range(64):
        emit("qmac", 5, 6, 7, check=False)
        emit("requant", 5, 5, 7, check=False)
    lines += [f"li s5, 0x{regs[5]:x}", "bne t0, s5, fail"]
    rng = random.Random(0x5852455157414C4C)
    for _ in range(512):
        a = rng.getrandbits(64)
        d = pack(rng.randrange(2**31), -rng.randrange(32), scale_only=True)
        lines += [f"li t1, 0x{a:x}", f"li t2, 0x{d:x}"]
        regs[6], regs[7] = a, d
        emit("requant", rng.choice((0, 5, 6, 7)), rng.choice((0, 5, 6)), 7)
    # Even a reserved descriptor on a branch's younger path must not trap.
    lines += ["li t2, -1"]
    for i in range(32):
        lines += [
            f"beq zero, zero, branch{i}",
            ".insn r 0x0b,1,0,t0,t1,t2",
            f"branch{i}:",
            f"li s5, 0x{regs[5]:x}",
            "bne t0, s5, fail",
        ]
    lines += [
        "j pass",
        ".section .rodata",
        ".balign 8",
        f"hazard_values: .dword 0xdeadbeef80000001, 0x{descriptor:x}",
        ".section .text.init",
    ]
    return envelope("\n".join(lines)), counts


def descriptor_traps():
    valid = pack(0x60000000, -1, scale_only=True)
    invalid = [valid | (1 << b) for b in (63, 31, 37)]
    invalid += [pack(1, 0) | (1 << 62) | (1 << b) for b in range(38, 62)]
    invalid += [pack(1, 0) | (r << 32) for r in range(32, 64)]
    invalid += [
        1 | ((lo & 255) << 46) | ((hi & 255) << 54)
        for lo, hi in ((1, 0), (127, -128), (0, -1), (-1, -128))
    ]
    # Every validation category includes rd=x0; aliases must retain source values.
    cases = [
        (d, rd, a, b, producer)
        for d in invalid
        for rd, a, b, producer in (
            (5, 6, 7, "li"),
            (0, 6, 7, "load"),
            (7, 6, 7, "csr"),
            (6, 6, 6, "load"),
            (5, 5, 5, "add"),
            (7, 6, 7, "mul"),
            (0, 6, 7, "div"),
        )
    ]
    lines = ["la a0, handler", "csrw mtvec, a0", "la s6, sentinel", "sd zero, 0(s6)"]
    data = [".section .rodata", ".balign 8"]
    for i, (d, rd, a, b, producer) in enumerate(cases):
        regs = {5: 42, 6: 0xDEADBEEF80000001, 7: valid}
        regs[b] = d
        word = (b << 20) | (a << 15) | (1 << 12) | (rd << 7) | 0xB
        lines += [f"li x{r}, 0x{v:x}" for r, v in regs.items()]
        lines += [
            f"li s2, 0x{regs[5]:x}",
            f"li s3, 0x{regs[6]:x}",
            f"li s4, 0x{regs[7]:x}",
            f"la s0, illegal{i}",
            f"li s1, 0x{word:x}",
            f"li s8, 0x{valid:x}",
            f"addi x{b}, s8, 0",
        ]  # stale valid descriptor before immediate producer
        if producer == "li":
            lines += [f"li x{b}, 0x{d:x}"]
        elif producer == "load":
            data += [f"descriptor{i}: .dword 0x{d:x}"]
            lines += [f"la s7, descriptor{i}", f"ld x{b}, 0(s7)"]
        elif producer == "csr":
            lines += [f"li s8, 0x{d:x}", "csrw mscratch, s8", f"csrr x{b}, mscratch"]
        elif producer in ("mul", "div"):
            lines += [
                f"li s8, 0x{d:x}",
                "li s9, 1",
                f"{'mul' if producer == 'mul' else 'divu'} x{b}, s8, s9",
            ]
        else:
            lines += [f"li s8, 0x{d:x}", f"addi x{b}, s8, 0"]
        lines += [
            f"illegal{i}:",
            f".word 0x{word:x}",
            ".insn r 0x0b,0,0,t0,t1,t2",
            "sd s8, 0(s6)",
        ]
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
        "bne t0, s2, fail",
        "bne t1, s3, fail",
        "bne t2, s4, fail",
        "ld t3, 0(s6)",
        "bnez t3, fail",
        "addi t3, s0, 12",
        "csrw mepc, t3",
        "mret",
    ]
    data += [".section .data", ".balign 8", "sentinel: .dword 0"]
    return envelope("\n".join(lines + data)), len(cases)


def compiler_replay(path, enabled):
    from tools.investigation.replay import verify_replay

    directory, _, workload, rows = verify_replay(path)
    if workload["configuration"] != "X2":
        raise ValueError("Xrequant replay requires X2 compiler evidence")
    qmac = sum(
        int(f.get("expected_xqmac8_instructions", 0)) for f in workload["fixtures"]
    )
    requant = sum(
        int(f.get("expected_xrequant_instructions", 0)) for f in workload["fixtures"]
    )
    if qmac + requant != sum(
        int(r["invocation"]["mix"]["custom"]["value"]) for r in rows
    ):
        raise ValueError("custom counts do not reconcile with retained Spike replay")
    kernel = (
        directory / json.loads((directory / "rv64/build.json").read_text())["binary"]
    )
    result = execute(
        "compiler-kernel-replay",
        enabled,
        kernel,
        qmac=qmac,
        requant=requant,
        timeout=2400,
    )
    text = (WORK / "compiler-kernel-replay.log").read_text()
    compared = [
        json.loads(line) for line in text.splitlines() if line.startswith('{"fixture":')
    ]
    if len(compared) != len(rows) or "compiler replay: PASS" not in text:
        raise ValueError("incomplete compiler replay output")
    for index, (actual, fixture) in enumerate(zip(compared, workload["fixtures"])):
        if actual != {
            "fixture": index,
            "status": fixture["expected_status"],
            "guards": True,
            "bytes_compared": fixture["output"]["bytes"],
            "first_difference": None,
        }:
            raise ValueError(f"compiler replay tensor mismatch: {index}")
    return result, {
        "artifact_id": directory.name,
        "fixtures": len(rows),
        "nodes": workload["nodes"],
        "cases": workload["cases"],
        "complete_output_bytes_compared": sum(x["bytes_compared"] for x in compared),
        "qmac": qmac,
        "requant": requant,
        "elf_sha256": digest(kernel),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--compiler-replay", type=Path)
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    integration = prepare(ROOT / ".deps/cvw", OVERLAY)
    built = {key: build(key, args.jobs) for key in integration["configurations"]}
    enabled = built["arch_project_xrequant"][0]
    cases = vectors()
    exported = WORK / "vectors.json"
    exported.write_text(
        json.dumps(
            {"contract_version": 1, "seed": "0x52455155414e54", "cases": cases},
            indent=2,
        )
        + "\n"
    )
    results = {}
    elf = compile_program("vectors", assembly(cases))
    for stall in (0, 31):
        name = "vectors" + ("-stalled" if stall else "")
        results[name] = execute(
            name, enabled, elf, requant=len(cases) + 64, stall=stall
        )
    program, counts = hazards()
    elf = compile_program("hazards", program)
    for stall in (0, 31):
        name = "hazards" + ("-stalled" if stall else "")
        results[name] = execute(name, enabled, elf, **counts, stall=stall)
        for gate in (
            "req_forward_m",
            "req_forward_w",
            "req_load",
            "req_mdu",
            "req_csr",
            "flushes",
        ):
            if not results[name]["metrics"][gate]:
                raise ValueError(f"hazard coverage missing: {name}/{gate}")
    program, traps = descriptor_traps()
    elf = compile_program("descriptor-traps", program)
    for stall in (0, 31):
        name = "descriptor-traps" + ("-stalled" if stall else "")
        results[name] = execute(name, enabled, elf, traps=traps, stall=stall)
        if results[name]["metrics"]["descriptor_faults"] != traps:
            raise ValueError("descriptor fault pipeline coverage differs")
    # Both exact encodings are legal; every other funct3/funct7 is reserved.
    words = [
        (f7 << 25) | (7 << 20) | (6 << 15) | (f3 << 12) | (5 << 7) | 0xB
        for f7 in range(128)
        for f3 in range(8)
        if (f7, f3) not in ((0, 0), (0, 1))
    ]
    words += [0x007302AB, 0x007302DB, 0x007302FB]
    elf = compile_program("invalid-encodings", qmac_tests.illegal(words))
    results["invalid-encodings"] = execute(
        "invalid-encodings", enabled, elf, traps=len(words)
    )
    for config, xlen, word in (
        ("arch_project_xrequant_off", 64, 0x0073128B),
        ("arch_project_xrequant_only", 64, 0x0073028B),
        ("arch_project_xrequant_rv32", 32, 0x0073128B),
        ("arch_project_xrequant_rv32", 32, 0x0073028B),
    ):
        name = config + f"-trap-{word:08x}"
        elf = compile_program(name, qmac_tests.illegal([word], xlen), xlen)
        results[name] = execute(name, built[config][0], elf, xlen, traps=1)
    for config, (binary, _) in built.items():
        xlen = 32 if config.endswith("rv32") else 64
        elf = compile_program(
            config + "-base", qmac_tests.compatibility(xlen, True), xlen
        )
        results[config + "-base"] = execute(config + "-base", binary, elf, xlen)
    # Prove independent enables in both directions and preserve Xqmac8 semantics.
    elf = compile_program("qmac-regression", qmac_assembly(qmac_vectors()))
    for config in ("arch_project_xrequant", "arch_project_xrequant_off"):
        name = config + "-qmac"
        results[name] = execute(name, built[config][0], elf, qmac=len(qmac_vectors()))
    program, count = qmac_tests.hazards()
    elf = compile_program("qmac-hazards", program)
    results["qmac-hazards"] = execute(
        "qmac-hazards", enabled, elf, qmac=count, stall=31
    )
    elf = compile_program("requant-only", assembly(cases))
    results["requant-only"] = execute(
        "requant-only",
        built["arch_project_xrequant_only"][0],
        elf,
        requant=len(cases) + 64,
    )
    replay = None
    if args.compiler_replay:
        results["compiler-kernel-replay"], replay = compiler_replay(
            args.compiler_replay, enabled
        )
    for name, expected in integration["files_sha256"].items():
        if digest(OVERLAY / name) != expected:
            raise ValueError(f"overlay changed during tests: {name}")
    if subprocess.check_output(["git", "-C", ROOT / ".deps/cvw", "diff", "HEAD", "--"]):
        raise ValueError("pinned Wally changed during tests")
    record = {
        "schema_version": 1,
        "status": "PASS",
        "integration": integration,
        "vectors": len(cases),
        "random_vectors": 10000,
        "dependency_chain": 64,
        "vectors_sha256": digest(exported),
        "hazard_counts": counts,
        "descriptor_traps": traps,
        "illegal_encodings": len(words),
        "builds": {k: v[1] for k, v in built.items()},
        "cases": results,
        "compiler_replay": replay,
        "scope": "functional RTL on actual Wally SoC with caches; physical timing/area unmeasured",
    }
    path = ROOT / "results/cvw/xrequant/verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
    print(path)


if __name__ == "__main__":
    main()
