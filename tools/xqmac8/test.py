#!/usr/bin/env python3
"""Execute native/ordinary/profile ISA vectors and trap/disassembly checks."""

import csv
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.xqmac8.build import build
from tools.xqmac8.runtime import digest, spike_command
from tools.xqmac8.vectors import vectors

PREFIX = str(ROOT / ".deps/xpack-riscv/bin/riscv-none-elf-")
OUTPUT = ROOT / "build/xqmac8/tests"


def run(command, **kw):
    return subprocess.run(
        list(map(str, command)),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        **kw,
    )


def assembly(cases):
    groups = {}
    for case in cases:
        if case["name"] == "accumulation-chain":
            continue
        groups.setdefault((case["rd"], case["rs1"], case["rs2"]), []).append(case)
    code = [
        ".option norvc",
        ".option norelax",
        ".section .text.init",
        ".globl _start, invoke, fixture_end",
        "_start:",
        "call invoke",
        "slli a0, a0, 1",
        "addi a0, a0, 1",
        "la a1, tohost",
        "sd a0, 0(a1)",
        "1: j 1b",
        "invoke:",
    ]
    data = [".section .rodata", ".balign 8"]
    for i, ((rd, rs1, rs2), rows) in enumerate(groups.items()):
        code += [
            f"la a0, group{i}",
            f"li a1, {len(rows)}",
            f"loop{i}:",
            "ld t0, 0(a0)",
            "ld t1, 8(a0)",
            "ld t2, 16(a0)",
            "ld a2, 24(a0)",
            f".insn r 0x0b, 0, 0, x{rd}, x{rs1}, x{rs2}",
            f"bne x{rd}, a2, fail",
            "addi a0, a0, 32",
            "addi a1, a1, -1",
            f"bnez a1, loop{i}",
        ]
        data += [f"group{i}:"]
        for row in rows:
            data += [
                ".dword "
                + ",".join("0x" + row["registers"][str(r)] for r in (5, 6, 7))
                + ",0x"
                + row["expected_rd"]
            ]
    chain = [c for c in cases if c["name"] == "accumulation-chain"]
    code += ["li t0, 0x" + chain[0]["registers"]["5"]]
    for row in chain:
        code += [
            "li t1, 0x" + row["registers"]["6"],
            "li t2, 0x" + row["registers"]["7"],
            ".insn r 0x0b, 0, 0, t0, t1, t2",
        ]
    code += [
        "li a2, 0x" + chain[-1]["expected_rd"],
        "bne t0, a2, fail",
        "li a0, 0",
        "ret",
        "fail:",
        "li a0, 1",
        "ret",
        "fixture_end:",
    ]
    return (
        "\n".join(
            code
            + data
            + [
                '.section .tohost,"aw",@progbits',
                ".balign 64",
                ".globl tohost",
                "tohost: .dword 0",
                ".globl fromhost",
                "fromhost: .dword 0",
            ]
        )
        + "\n"
    )


def compile_asm(name, text, rv32=False):
    source, obj, elf = (OUTPUT / (name + suffix) for suffix in (".S", ".o", ".elf"))
    source.write_text(text)
    run(
        [
            PREFIX + "as",
            "-march=rv32imc_zicsr" if rv32 else "-march=rv64imc_zicsr",
            "-mabi=ilp32" if rv32 else "-mabi=lp64",
            source,
            "-o",
            obj,
        ]
    )
    script = ROOT / "tflm/platform/rv64imc/link.ld"
    if rv32:
        script = OUTPUT / "rv32.ld"
        script.write_text(
            "OUTPUT_ARCH(riscv)\nENTRY(_start)\nSECTIONS { . = 0x80000000; .text : { *(.text.init) *(.text*) } . = ALIGN(4096); .tohost : { *(.tohost) } }\n"
        )
    run(
        [
            PREFIX + "ld",
            "-m",
            "elf32lriscv" if rv32 else "elf64lriscv",
            "-T",
            script,
            obj,
            "-o",
            elf,
        ]
    )
    return elf


def trap_fixture(word, rv32=False):
    store = "sw" if rv32 else "sd"
    return f""".option norvc
.section .text.init
.globl _start
_start:
  la a0, handler
  csrw mtvec, a0
  .word {word}
  li a0, 3
  j exit
.balign 4
handler:
  csrr a1, mcause
  li a2, 2
  li a0, 3
  bne a1, a2, exit
  li a0, 1
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


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = {v: build(v) for v in ("ordinary", "profile")}
    cases = vectors()
    (OUTPUT / "vectors.json").write_text(
        json.dumps(
            {"contract_version": 1, "seed": "0x514d414338", "cases": cases}, indent=2
        )
        + "\n"
    )
    elf = compile_asm("vectors", assembly(cases))
    # Native emulation is tested against the same independent arbitrary-precision oracle.
    host = OUTPUT / "native.cc"
    rows = []
    for c in cases:
        if c["rd"]:
            regs = c["registers"]
            rows.append(
                "{"
                + ",".join(
                    "0x" + v + "ull"
                    for v in (
                        regs[str(c["rd"])],
                        regs[str(c["rs1"])],
                        regs[str(c["rs2"])],
                        c["expected_rd"],
                    )
                )
                + "}"
            )
    host.write_text(
        '#include "kernels/xqmac8/dot8.h"\n#include <cstdint>\nint main() { uint64_t rows[][4] = {'
        + ",".join(rows)
        + "};\nfor (auto &r: rows) { uint32_t u = r[0]; int32_t a = u < 0x80000000u ? int32_t(u) : -1-int32_t(~u); if (uint64_t(int64_t(arch_project::xqmac8(a,r[1],r[2]))) != r[3]) return 1; }\n"
        + "alignas(8) int8_t bytes[24]; for (unsigned i=0;i<24;++i) bytes[i]=i;\n"
        + "for (int offset=0;offset<8;++offset) { uint64_t expected=0; for(unsigned lane=0;lane<8;++lane) expected |= uint64_t(bytes[offset+lane]) << (8*lane); if (arch_project::packed8<1>(bytes+offset)!=expected) return 2; }\n"
        + "if (arch_project::packed8<8>(bytes)!=0x0706050403020100ull || arch_project::packed8<4>(bytes+4)!=0x0b0a090807060504ull) return 3; }\n"
    )
    cxx = (
        "/Library/Developer/CommandLineTools/usr/bin/clang++"
        if sys.platform == "darwin"
        else "c++"
    )
    flags = (
        ["-isysroot", "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"]
        if sys.platform == "darwin"
        else []
    )
    run(
        [
            cxx,
            "-std=c++17",
            "-O1",
            "-fsanitize=address,undefined",
            *flags,
            "-I",
            ROOT,
            host,
            "-o",
            OUTPUT / "native",
        ]
    )
    run([OUTPUT / "native"])
    nm = run([PREFIX + "nm", elf]).stdout
    start = next(
        line.split()[0] for line in nm.splitlines() if line.endswith(" _start")
    )
    entry = next(
        line.split()[0] for line in nm.splitlines() if line.endswith(" invoke")
    )
    config = OUTPUT / "regions.txt"
    # The fixture exits through HTIF; use explicit start/stop PCs around all custom operations.
    end = next(
        line.split()[0] for line in nm.splitlines() if line.endswith(" fixture_end")
    )
    config.write_text(f"code 0x{start} 0x{end}\nregion invoke 0x{entry}\n")
    for variant in records:
        result = run([*spike_command("X1", variant), elf])
        (OUTPUT / (variant + "-stderr.txt")).write_text(result.stderr)
    from tools.xqmac8.runtime import decode

    for repeat in (1, 2):
        prefix = OUTPUT / f"profile{repeat}"
        run(
            [
                *spike_command("X1", "profile"),
                f"--profile-config={config}",
                f"--profile-output={prefix}",
                elf,
            ]
        )
        with Path(str(prefix) + ".events.csv").open() as f:
            events = list(csv.DictReader(f))
        with Path(str(prefix) + ".pcs.csv").open() as f:
            pcs = list(csv.DictReader(f))
        custom = sum(
            int(r["count"]) for r in pcs if decode(int(r["bits"]), int(r["length"]))
        )
        if (
            len(events) != 1
            or events[0]["complete"] != "1"
            or events[0]["status"] != "0"
            or custom != len(cases)
        ):
            raise ValueError("ISA fixture retirement count/completion differs")
    for suffix in (".events.csv", ".pcs.csv"):
        if (OUTPUT / ("profile1" + suffix)).read_bytes() != (
            OUTPUT / ("profile2" + suffix)
        ).read_bytes():
            raise ValueError("ISA fixture profiles differ")
    logged = run([*spike_command("X1"), "-l", elf])
    if "xqmac8" not in logged.stderr:
        raise ValueError("Spike disassembler does not recognize Xqmac8")
    # Disabled extension and reserved neighboring encodings must trap cleanly.
    disabled = compile_asm("disabled", trap_fixture("0x0073028b"))
    run([*spike_command("B1"), disabled])
    for word in ("0x0073128b", "0x0273028b"):
        invalid = compile_asm("invalid-" + word, trap_fixture(word))
        run([*spike_command("X1"), invalid])
    rv32 = compile_asm("rv32", trap_fixture("0x0073028b", True), True)
    ordinary = spike_command("X1")
    run([*ordinary[:-1], "--isa=rv32imc_xqmac8", rv32])
    report = {
        "status": "PASS",
        "vectors": len(cases),
        "random_vectors": 10000,
        "native_sanitized": "PASS",
        "ordinary": "PASS",
        "profile": "PASS",
        "disassembly": "PASS",
        "disabled_extension": "PASS",
        "invalid_encodings": "PASS",
        "rv32_trap": "PASS",
        "elf_sha256": digest(elf),
        "profile_custom_retirements": len(cases),
        "repeat_profiles_identical": True,
        "vectors_sha256": digest(OUTPUT / "vectors.json"),
        "extensions": records,
    }
    (OUTPUT / "verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"Xqmac8 ISA: PASS ({len(cases)} vectors, native sanitizers, both Spike variants, disassembly and traps)"
    )


if __name__ == "__main__":
    main()
