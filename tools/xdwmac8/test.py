#!/usr/bin/env python3
"""Verify bank arithmetic, state transfers, traps, context restore and hart isolation."""

import csv
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.xdwmac8.contract import NAMES, encode, decode, oracle
from tools.xdwmac8.build import build
from tools.custom_isa import spike_command, extension_identity
from tools.xqmac8.runtime import digest
from tools.xqmac8 import test as fixtures

OUT = ROOT / "build/xdwmac8/tests"


def run(command):
    r = subprocess.run(
        list(map(str, command)),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if r.returncode:
        raise RuntimeError(f"{command}: {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


def program(code, data=()):
    return (
        "\n".join(
            [
                ".option norvc",
                ".option norelax",
                ".section .text.init",
                ".globl _start,invoke,fixture_end",
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


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fixtures.OUTPUT = OUT
    for v in ("ordinary", "profile"):
        build(v)
    rng = random.Random(0x44574D414338)
    cases = []
    code = []
    data = []
    # Initial hart reset state and non-destructive reads, including destination x0.
    for i in range(4):
        code += [
            f".word {encode(f'xdwget{i}', rd=5)}",
            "bnez t0,fail",
            f".word {encode(f'xdwget{i}')}",
        ]
    for group, (a_reg, w_reg) in enumerate(((6, 7), (6, 6), (0, 7), (6, 0), (0, 0))):
        count = 10000 if group == 0 else 64
        code += [f"la a0,rows{group}", f"li a1,{count}", f"loop{group}:"]
        for pair in range(4):
            code += [f"ld t0,{8 * pair}(a0)", f".word {encode(f'xdwset{pair}', rs1=5)}"]
        code += [
            "ld t1,32(a0)",
            "ld t2,40(a0)",
            f".word {encode('xdwmac8', rs1=a_reg, rs2=w_reg)}",
        ]
        for pair in range(4):
            code += [
                f".word {encode(f'xdwget{pair}', rd=5)}",
                f"ld a2,{48 + 8 * pair}(a0)",
                "bne t0,a2,fail",
            ]
        code += ["addi a0,a0,80", "addi a1,a1,-1", f"bnez a1,loop{group}"]
        data += [".balign 8", f"rows{group}:"]
        for j in range(count):
            lanes = [rng.getrandbits(32) for _ in range(8)]
            a, w = rng.getrandbits(64), rng.getrandbits(64)
            if j < 4:
                a = w = (0, 0x8080808080808080, 0x7F7F7F7F7F7F7F, (1 << 64) - 1)[j]
            regs = {0: 0, 6: a, 7: w}
            expected = oracle(lanes, regs[a_reg], regs[w_reg])
            pairs = lambda x: [x[2 * k] | (x[2 * k + 1] << 32) for k in range(4)]
            data += [
                ".dword "
                + ",".join(
                    f"0x{x:016x}" for x in (*pairs(lanes), a, w, *pairs(expected))
                )
            ]
            cases.append(
                dict(initial=lanes, a=regs[a_reg], w=regs[w_reg], expected=expected)
            )
    # Explicit save/modify/restore context and dependency chains.
    for i in range(4):
        code += [f"li t0,{i + 1}", f".word {encode(f'xdwset{i}', rs1=5)}"]
    code += ["la a0,saved"]
    for i in range(4):
        code += [
            f".word {encode(f'xdwget{i}', rd=5)}",
            f"sd t0,{i * 8}(a0)",
            f".word {encode(f'xdwset{i}')}",
        ]
    for i in range(4):
        code += [f"ld t0,{i * 8}(a0)", f".word {encode(f'xdwset{i}', rs1=5)}"]
    code += ["li t1,0x0101010101010101", "li t2,0x0101010101010101"]
    for _ in range(64):
        code += [f".word {encode('xdwmac8', rs1=6, rs2=7)}"]
    for i in range(4):
        code += [
            f".word {encode(f'xdwget{i}', rd=5)}",
            f"li a2,{(64 << 32) | (65 + i)}",
            "bne t0,a2,fail",
        ]
    code += [
        f".word {encode('xdwset2')}",
        f".word {encode('xdwget2', rd=5)}",
        "bnez t0,fail",
        f".word {encode('xdwget1', rd=5)}",
        f"li a2,{(64 << 32) | 66}",
        "bne t0,a2,fail",
    ]
    data += [".balign 8", "saved: .zero 32"]
    elf = fixtures.compile_asm("vectors", program(code, data))
    (OUT / "vectors.json").write_text(
        json.dumps(
            dict(contract_version=1, seed="0x44574d414338", cases=cases), indent=2
        )
        + "\n"
    )
    # Native implementation independently checked against Python lane arithmetic.
    native = OUT / "native.cc"
    rows = []
    for c in cases:
        pairs = lambda xs: [xs[i * 2] | (xs[i * 2 + 1] << 32) for i in range(4)]
        rows.append(
            "{"
            + ",".join(
                f"0x{n:016x}ull"
                for n in (*pairs(c["initial"]), c["a"], c["w"], *pairs(c["expected"]))
            )
            + "}"
        )
    native.write_text(
        '#include "kernels/xdwmac8/bank.h"\n#include <thread>\nconst uint64_t rows[][10]={'
        + ",".join(rows)
        + "};\nint main(){arch_project::dw::Bank b; for(auto&r:rows){b.set<0>(r[0]);b.set<1>(r[1]);b.set<2>(r[2]);b.set<3>(r[3]);b.mac(r[4],r[5]);if(b.get<0>()!=r[6]||b.get<1>()!=r[7]||b.get<2>()!=r[8]||b.get<3>()!=r[9])return 1;} b.set<0>(123); bool ok=false;std::thread t([&]{arch_project::dw::Bank c;ok=c.get<0>()==0;c.set<0>(456);});t.join();return !ok||b.get<0>()!=123;}"
    )
    cxx = (
        "/Library/Developer/CommandLineTools/usr/bin/clang++"
        if sys.platform == "darwin"
        else "c++"
    )
    sdk = (
        ["-isysroot", "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"]
        if sys.platform == "darwin"
        else []
    )
    run(
        [
            cxx,
            "-std=c++17",
            "-O1",
            "-pthread",
            "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all",
            *sdk,
            "-I",
            ROOT,
            native,
            "-o",
            OUT / "native",
        ]
    )
    run([OUT / "native"])
    for v in ("ordinary", "profile"):
        run([*spike_command("X4", v), elf])
    nm = run([fixtures.PREFIX + "nm", "-n", elf]).stdout
    addr = lambda name: next(
        l.split()[0] for l in nm.splitlines() if l.endswith(" " + name)
    )
    config = OUT / "regions.txt"
    config.write_text(
        f"code 0x{addr('_start')} 0x{addr('fixture_end')}\nregion invoke 0x{addr('invoke')}\n"
    )
    for rep in (1, 2):
        run(
            [
                *spike_command("X4", "profile"),
                f"--profile-config={config}",
                f"--profile-output={OUT / f'run{rep}'}",
                elf,
            ]
        )
    for suffix in (".events.csv", ".pcs.csv"):
        if (OUT / ("run1" + suffix)).read_bytes() != (
            OUT / ("run2" + suffix)
        ).read_bytes():
            raise ValueError("bank profiles differ")
    with (OUT / "run1.pcs.csv").open() as f:
        counts = {name: 0 for name in NAMES}
        for row in csv.DictReader(f):
            name = decode(int(row["bits"]), int(row["length"]))
            if name:
                counts[name] += int(row["count"])
    if counts["xdwmac8"] != len(cases) + 64:
        raise ValueError("bank MAC retirement mismatch")
    # Invalid encodings preserve architectural bank and exact trap location/value.
    reserved = [
        encode("xdwmac8", rs1=6, rs2=7) | (1 << 7),
        encode("xdwmac8") | (1 << 25),
    ]
    reserved += [
        0x300B | (4 << 25),
        0x300B | (1 << 20),
        0x300B | (1 << 7),
        0x400B | (4 << 25),
        0x400B | (1 << 15),
        0x400B | (1 << 20),
    ]
    for i, word in enumerate(reserved):
        text = fixtures.trap_fixture(word)
        text = text.replace(
            f"  .word {word}",
            f"  li t1,123\n  .word {encode('xdwset0', rs1=6)}\nfault:\n  .word {word}",
        )
        text = text.replace(
            "  li a0, 1\nexit:",
            f"""  csrr a1,mepc
  la a2,fault
  bne a1,a2,exit
  csrr a1,mtval
  li a2,{word}
  bne a1,a2,exit
  .word {encode("xdwget0", rd=6)}
  li a2,123
  bne t1,a2,exit
  li a0, 1
exit:""",
        )
        trap = fixtures.compile_asm(f"reserved-{i}", text)
        for v in ("ordinary", "profile"):
            run([*spike_command("X4", v), trap])
    for rv32 in (False, True):
        word = encode("xdwmac8", rs1=6, rs2=7)
        trap = fixtures.compile_asm(
            "rv32" if rv32 else "disabled", fixtures.trap_fixture(word, rv32), rv32
        )
        for v in ("ordinary", "profile"):
            cmd = spike_command("X4", v)
            cmd[-1] = "--isa=rv32imc_xdwmac8" if rv32 else "--isa=rv64imc"
            run([*cmd, trap])
    # Two harts deliberately interleave bank mutations through RAM handshakes.
    multi = program(
        [
            "csrr t3,mhartid",
            "la a0,flags",
            "bnez t3,hart1",
            "li t0,123",
            f".word {encode('xdwset0', rs1=5)}",
            "li t1,1",
            "sd t1,0(a0)",
            "fence rw,rw",
            "wait1: ld t1,8(a0)",
            "beqz t1,wait1",
            "fence rw,rw",
            f".word {encode('xdwget0', rd=5)}",
            "li t1,123",
            "bne t0,t1,fail",
            "li t1,1",
            "sd t1,16(a0)",
            "fence rw,rw",
            "wait3: ld t1,24(a0)",
            "beqz t1,wait3",
            "j done",
            "hart1: ld t1,0(a0)",
            "beqz t1,hart1",
            "fence rw,rw",
            f".word {encode('xdwget0', rd=5)}",
            "bnez t0,fail",
            "li t0,456",
            f".word {encode('xdwset0', rs1=5)}",
            "li t1,1",
            "sd t1,8(a0)",
            "fence rw,rw",
            "wait2: ld t1,16(a0)",
            "beqz t1,wait2",
            "fence rw,rw",
            f".word {encode('xdwget0', rd=5)}",
            "li t1,456",
            "bne t0,t1,fail",
            "li t1,1",
            "sd t1,24(a0)",
            "fence rw,rw",
            "park: j park",
            "done:",
        ],
        [".balign 8", "flags: .zero 32"],
    )
    multi = fixtures.compile_asm("two-harts", multi)
    for v in ("ordinary", "profile"):
        run([*spike_command("X4", v), "-p2", multi])
    report = dict(
        status="PASS",
        vectors=len(cases),
        native_sanitizers=True,
        native_thread_isolation=True,
        spike_two_hart_isolation=True,
        context_restore=True,
        dependent_macs=64,
        precise_traps=len(reserved),
        disabled_rv32=True,
        repeated_profiles_identical=True,
        counts=counts,
        elf_sha256=digest(elf),
        vectors_sha256=digest(OUT / "vectors.json"),
        extensions={v: extension_identity(v, "X4") for v in ("ordinary", "profile")},
    )
    (OUT / "verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"Xdwmac8 ISA: PASS ({len(cases)} vectors, context/aliases/traps, two profiles)"
    )


if __name__ == "__main__":
    main()
