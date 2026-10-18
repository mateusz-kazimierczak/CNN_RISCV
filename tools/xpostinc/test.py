#!/usr/bin/env python3
"""Execute Xpostinc memory, alias, precise-fault and retirement tests in Spike."""

import csv
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.custom_isa import extension_identity, spike_command
from tools.xpostinc.build import build
from tools.xpostinc.contract import (
    LOADS,
    MASK64,
    NAMES,
    STORES,
    decode,
    encode,
    load_oracle,
)
from tools.xqmac8 import test as fixtures
from tools.xqmac8.runtime import digest

OUTPUT = ROOT / "build/xpostinc/tests"
STRIDES = (-2048, -1152, -8, -1, 0, 1, 8, 672, 2047)


def run(command):
    result = subprocess.run(
        list(map(str, command)),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"{command}: {result.returncode}\n{result.stdout}\n{result.stderr}"
        )
    return result


def finish(code, data):
    return (
        "\n".join(
            [
                ".option norvc",
                ".option norelax",
                ".section .text.init",
                ".globl _start, invoke, fixture_end",
                "_start:",
                "call invoke",
                "slli a0,a0,1",
                "addi a0,a0,1",
                "la a1,tohost",
                "sd a0,0(a1)",
                "1: j 1b",
                "invoke:",
                *code,
                "li a0,0",
                "ret",
                "fail: li a0,1",
                "ret",
                "fixture_end:",
                ".section .data",
                ".balign 64",
                "scratch: .zero 64",
                *data,
                '.section .tohost,"aw",@progbits',
                ".balign 64",
                ".globl tohost,fromhost",
                "tohost: .dword 0",
                "fromhost: .dword 0",
            ]
        )
        + "\n"
    )


def vector_program():
    rng = random.Random(0x504F5354494E43)
    code, data, cases = [], [], []
    for name in NAMES:
        for stride in STRIDES:
            group = len(cases)
            label = f"group{group}"
            code += [
                f"la a0,{label}",
                "li a1,128",
                f"loop{group}:",
                "la t1,scratch",
                "ld t0,0(a0)",
                *(
                    ["sd t0,0(t1)"]
                    if name in LOADS
                    else ["li a4,0xa5b6c7d8e9fa0b1c", "sd a4,0(t1)"]
                ),
                f".word {encode(name, 5, 6, stride)}",
                "la a2,scratch",
                f"li a3,{stride}",
                "add a2,a2,a3",
                "bne t1,a2,fail",
                "ld a2,8(a0)",
            ]
            if name in LOADS:
                code += ["bne t0,a2,fail"]
            else:
                code += [
                    "la a3,scratch",
                    "ld a3,0(a3)",
                    "bne a3,a2,fail",
                    "ld a3,0(a0)",
                    "bne t0,a3,fail",
                ]
            code += ["addi a0,a0,16", "addi a1,a1,-1", f"bnez a1,loop{group}"]
            data += [".balign 8", label + ":"]
            for i in range(128):
                raw = (
                    (0, MASK64, 0x8000000080008080, 0x7FFFFFFF7FFF7F7F)[i]
                    if i < 4
                    else rng.getrandbits(64)
                )
                width = 1 << ((LOADS if name in LOADS else STORES).index(name) & 3)
                expected = (
                    load_oracle(name, raw.to_bytes(8, "little")[:width])
                    if name in LOADS
                    else (
                        (0xA5B6C7D8E9FA0B1C & ~((1 << (width * 8)) - 1))
                        | (raw & ((1 << (width * 8)) - 1))
                    )
                )
                data += [f".dword 0x{raw:016x},0x{expected:016x}"]
                cases.append(
                    {
                        "name": name,
                        "increment": stride,
                        "source": f"{raw:016x}",
                        "expected": f"{expected:016x}",
                    }
                )
    # Consecutive dependent pointers, old-base store alias, zero-register source/destination.
    code += ["la t1,scratch", "li t0,-1", "sd t0,0(t1)"]
    for _ in range(8):
        code += [f".word {encode('xlbpi', 0, 6, 1)}"]
    code += [
        "la a2,scratch",
        "addi a2,a2,8",
        "bne t1,a2,fail",
        "la t1,scratch",
        f".word {encode('xsdpi', 6, 6, 8)}",
        "la a2,scratch",
        "ld a3,0(a2)",
        "bne a2,a3,fail",
        "addi a2,a2,8",
        "bne a2,t1,fail",
        "la t1,scratch",
        f".word {encode('xsdpi', 0, 6, 0)}",
        "ld a2,0(t1)",
        "bnez a2,fail",
        "li t0,-1",
        f".word {encode('xsbpi', 5, 6, 1)}",
        "la a2,scratch",
        "ld a3,0(a2)",
        "li a4,255",
        "bne a3,a4,fail",
    ]
    return finish(code, data), cases, len(cases) + 11


def trap_program(word, cause, address="scratch", rv32=False):
    store = "sw" if rv32 else "sd"
    load = "lw" if rv32 else "ld"
    expected_value = 0x12345678
    mtval = (
        str(word)
        if cause == 2
        else (
            "0"
            if address == "zero"
            else "0x40000000"
            if address == "unmapped"
            else None
        )
    )
    setup = [
        "li t0,0x12345678",
        "la t1,scratch",
        "li a4,0x11223344",
        f"{store} a4,0(t1)",
    ]
    if address == "misaligned":
        setup += ["addi t1,t1,1"]
    if address == "unmapped":
        setup += ["li t1,0x40000000"]
    if address == "zero":
        setup += ["li t1,0"]
    setup += ["mv a3,t1"]
    check_mtval = [f"li a2,{mtval}"] if mtval is not None else ["mv a2,a3"]
    return (
        "\n".join(
            [
                ".option norvc",
                ".section .text.init",
                ".globl _start",
                "_start:",
                "la a0,handler",
                "csrw mtvec,a0",
                *setup,
                f"fault: .word {word}",
                "li a0,3",
                "j exit",
                ".balign 4",
                "handler:",
                "csrr a1,mcause",
                f"li a2,{cause}",
                "li a0,3",
                "bne a1,a2,exit",
                "csrr a1,mepc",
                "la a2,fault",
                "bne a1,a2,exit",
                "csrr a1,mtval",
                *check_mtval,
                "bne a1,a2,exit",
                "bne t1,a3,exit",
                f"li a2,{expected_value}",
                "bne t0,a2,exit",
                "la a2,scratch",
                f"{load} a1,0(a2)",
                "li a2,0x11223344",
                "bne a1,a2,exit",
                "li a0,1",
                "exit:",
                "la a1,tohost",
                f"{store} a0,0(a1)",
                "1: j 1b",
                ".section .data",
                ".balign 64",
                "scratch: .zero 64",
                '.section .tohost,"aw",@progbits',
                ".balign 64",
                ".globl tohost,fromhost",
                "tohost: .dword 0",
                "fromhost: .dword 0",
            ]
        )
        + "\n"
    )


def native_check():
    types = (
        ("int8_t", "xlbpi"),
        ("int16_t", "xlhpi"),
        ("int32_t", "xlwpi"),
        ("uint64_t", "xldpi"),
        ("uint8_t", "xlbupi"),
        ("uint16_t", "xlhupi"),
        ("uint32_t", "xlwupi"),
    )
    rng = random.Random(0x504F5354)
    code = [
        '#include "kernels/xpostinc/memory.h"',
        "#include <cstring>",
        "int main() { alignas(8) int8_t memory[8];",
    ]
    for typ, name in types:
        width = 1 << (LOADS.index(name) & 3)
        for stride in STRIDES:
            for _ in range(16):
                raw = rng.getrandbits(64)
                expected = load_oracle(name, raw.to_bytes(8, "little")[:width])
                mask = (1 << (width * 8)) - 1
                stored = (0xA5B6C7D8E9FA0B1C & ~mask) | (raw & mask)
                code += [
                    "{",
                    f"uint64_t raw = 0x{raw:016x}ull;",
                    "__builtin_memcpy(memory,&raw,8); const int8_t* p=memory;",
                    f"if (uint64_t(arch_project::postinc::load<{typ},{stride}>(p)) != 0x{expected:016x}ull) return 1;",
                    f"if (uintptr_t(p) != uintptr_t(memory)+uintptr_t({stride})) return 2;",
                    "raw=0xa5b6c7d8e9fa0b1cull; __builtin_memcpy(memory,&raw,8); int8_t* q=memory;",
                    f"arch_project::postinc::store<{typ},{stride}>(q,static_cast<{typ}>(0x{raw:016x}ull));",
                    "__builtin_memcpy(&raw,memory,8);",
                    f"if (raw != 0x{stored:016x}ull || uintptr_t(q) != uintptr_t(memory)+uintptr_t({stride})) return 3;",
                    "}",
                ]
    code += ["return 0; }"]
    source = OUTPUT / "native.cc"
    source.write_text("\n".join(code) + "\n")
    cxx = (
        "/Library/Developer/CommandLineTools/usr/bin/clang++"
        if sys.platform == "darwin"
        else "c++"
    )
    run(
        [
            cxx,
            "-std=c++17",
            "-O1",
            "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all",
            *(
                ["-isysroot", "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"]
                if sys.platform == "darwin"
                else []
            ),
            "-I",
            ROOT,
            source,
            "-o",
            OUTPUT / "native",
        ]
    )
    run([OUTPUT / "native"])
    return {
        "status": "PASS",
        "load_cases": len(types) * len(STRIDES) * 16,
        "store_cases": len(types) * len(STRIDES) * 16,
        "source_sha256": digest(source),
        "header_sha256": digest(ROOT / "kernels/xpostinc/memory.h"),
    }


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fixtures.OUTPUT = OUTPUT
    for variant in ("ordinary", "profile"):
        build(variant)
    native = native_check()
    source, cases, expected = vector_program()
    elf = fixtures.compile_asm("vectors", source)
    vectors = OUTPUT / "vectors.json"
    vectors.write_text(
        json.dumps(
            {"contract_version": 1, "seed": "0x504f5354494e43", "cases": cases},
            indent=2,
        )
        + "\n"
    )
    for variant in ("ordinary", "profile"):
        run([*spike_command("X3", variant), elf])
    symbols = run([fixtures.PREFIX + "nm", "-n", elf]).stdout
    addr = lambda name: next(
        line.split()[0] for line in symbols.splitlines() if line.endswith(" " + name)
    )
    config = OUTPUT / "regions.txt"
    config.write_text(
        f"code 0x{addr('_start')} 0x{addr('fixture_end')}\nregion invoke 0x{addr('invoke')}\n"
    )
    for repeat in (1, 2):
        prefix = OUTPUT / f"profile{repeat}"
        run(
            [
                *spike_command("X3", "profile"),
                f"--profile-config={config}",
                f"--profile-output={prefix}",
                elf,
            ]
        )
        with Path(str(prefix) + ".pcs.csv").open() as f:
            count = sum(
                int(r["count"])
                for r in csv.DictReader(f)
                if decode(int(r["bits"]), int(r["length"]))
            )
        if count != expected:
            raise ValueError(f"vector retirements {count} != {expected}")
    for suffix in (".events.csv", ".pcs.csv"):
        if (OUTPUT / ("profile1" + suffix)).read_bytes() != (
            OUTPUT / ("profile2" + suffix)
        ).read_bytes():
            raise ValueError("ISA profiles differ")
    traps = []
    for name in NAMES:
        width = 1 << ((LOADS if name in LOADS else STORES).index(name) & 3)
        word = encode(name, 5, 6, 8)
        traps.append((name + "-access", word, 7 if name in STORES else 5, "unmapped"))
        if width > 1:
            traps.append(
                (name + "-misaligned", word, 6 if name in STORES else 4, "misaligned")
            )
    for name in LOADS:
        traps.append((name + "-alias", encode(name, 6, 6, 8), 2, "scratch"))
    traps += [("reserved-load", 0x702B | (5 << 7) | (6 << 15), 2, "scratch")]
    traps += [
        (f"reserved-store-{f}", 0x7B | (f << 12) | (5 << 7) | (6 << 15), 2, "scratch")
        for f in range(4, 8)
    ]
    traps += [
        ("x0-load-fault", encode("xldpi", 0, 6, 8), 5, "unmapped"),
        ("x0-base-fault", encode("xlbpi", 5, 0, 8), 5, "zero"),
        ("x0-store-base-fault", encode("xsdpi", 5, 0, 8), 7, "zero"),
        ("alias-priority", encode("xldpi", 6, 6, 8), 2, "misaligned"),
    ]
    for label, word, cause, address in traps:
        fixture = fixtures.compile_asm(label, trap_program(word, cause, address))
        for variant in ("ordinary", "profile"):
            run([*spike_command("X3", variant), fixture])
    for rv32 in (False, True):
        word = encode("xldpi", 5, 6, 8)
        fixture = fixtures.compile_asm(
            "rv32" if rv32 else "disabled", trap_program(word, 2, rv32=rv32), rv32
        )
        for variant in ("ordinary", "profile"):
            cmd = spike_command("X3", variant)
            cmd[-1] = "--isa=rv32imc_xpostinc" if rv32 else "--isa=rv64imc"
            run([*cmd, fixture])
    tiny = fixtures.compile_asm(
        "disasm", finish(["la t1,scratch", f".word {encode('xldpi', 5, 6, 8)}"], [])
    )
    if "xldpi" not in run([*spike_command("X3"), "-l", tiny]).stderr:
        raise ValueError("missing disassembly")
    report = {
        "status": "PASS",
        "native": native,
        "vectors": len(cases),
        "postincrement_retirements": expected,
        "repeated_profiles_identical": True,
        "precise_fault_cases": len(traps),
        "disabled_and_rv32": True,
        "vectors_sha256": digest(vectors),
        "elf_sha256": digest(elf),
        "extensions": {v: extension_identity(v, "X3") for v in ("ordinary", "profile")},
    }
    (OUTPUT / "verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"Xpostinc ISA: PASS ({len(cases)} vectors, {len(traps)} precise faults, disabled/RV32, two profiles)"
    )


if __name__ == "__main__":
    main()
