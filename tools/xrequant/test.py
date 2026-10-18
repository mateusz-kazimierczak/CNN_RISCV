#!/usr/bin/env python3
"""Oracle, pinned-reference, alias, trap and repeated-profile verification."""

from collections import defaultdict
import csv
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.xrequant.contract import pack, oracle, decode, MASK64
from tools.xrequant.build import build
from tools.custom_isa import spike_command, extension_identity
from tools.xqmac8.runtime import digest
from tools.xqmac8 import test as fixtures

OUTPUT = ROOT / "build/xrequant/tests"
fixtures.OUTPUT = OUTPUT


def run(command):
    r = subprocess.run(
        list(map(str, command)), capture_output=True, text=True, timeout=180
    )
    if r.returncode:
        raise RuntimeError(f"{command}: {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


def vectors():
    rng = random.Random(0x52455155414E54)
    cases = []

    def add(a, d, rd=5, rs1=6, rs2=7, name="directed"):
        regs = {5: rng.getrandbits(64), 6: a, 7: d, 0: 0}
        regs[rs2] = d if rs2 else 0
        if rs1 != rs2:
            regs[rs1] = a if rs1 else 0
        expected = oracle(regs[rs1], regs[rs2]) if rd else 0
        cases.append(
            dict(
                name=name,
                rd=rd,
                rs1=rs1,
                rs2=rs2,
                registers={str(k): f"{v:016x}" for k, v in regs.items()},
                expected_rd=f"{expected:016x}",
            )
        )

    for scale in (False, True):
        for r in range(32):
            for m in (0, 1, 1 << 30, 0x7FFFFFFF):
                for a in (0, 1, 3, 0x7FFFFFFF, 0x80000000, MASK64, 0xDEADBEEF00000001):
                    add(
                        a,
                        pack(m, -r, scale_only=scale)
                        if scale
                        else pack(m, -r, -128, -128, 127),
                    )
    for _ in range(10000):
        scale = bool(rng.getrandbits(1))
        lo = rng.randint(-128, 127)
        hi = rng.randint(lo, 127)
        d = (
            pack(rng.randrange(2**31), -rng.randrange(32), scale_only=True)
            if scale
            else pack(
                rng.randrange(2**31), -rng.randrange(32), rng.randint(-128, 127), lo, hi
            )
        )
        add(rng.getrandbits(64), d, name="random")
    for rd, rs1, rs2 in (
        (5, 5, 7),
        (5, 6, 5),
        (5, 6, 6),
        (5, 5, 5),
        (0, 6, 7),
        (5, 0, 7),
        (5, 6, 0),
    ):
        for _ in range(64):
            add(
                rng.getrandbits(64),
                pack(rng.randrange(2**31), -rng.randrange(32), scale_only=True),
                rd,
                rs1,
                rs2,
                "alias-or-x0",
            )
    # Directed double rounding, clipping, and wide zero-point addition.
    for m, s, z, lo, hi in (
        (1 << 30, -1, 0, -128, 127),
        (0x7FFFFFFF, 0, 127, -128, 127),
        (0x7FFFFFFF, 0, -128, -128, 127),
        (1 << 30, 0, 3, -7, 17),
    ):
        for a in (1, 0x7FFFFFFF, 0x80000000, MASK64):
            add(a, pack(m, s, z, lo, hi))
    return cases


def assembly(cases):
    code = [
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
    ]
    data = [".section .rodata", ".balign 8"]
    groups = defaultdict(list)
    for c in cases:
        groups[(c["rd"], c["rs1"], c["rs2"])].append(c)
    for idx, ((rd, a, d), rows) in enumerate(groups.items()):
        code += [
            f"la a0,group{idx}",
            f"li a1,{len(rows)}",
            f"loop{idx}:",
            "ld t0,0(a0)",
            "ld t1,8(a0)",
            "ld t2,16(a0)",
            "ld a2,24(a0)",
            f".insn r 0x0b,1,0,x{rd},x{a},x{d}",
            f"bne x{rd},a2,fail",
            "addi a0,a0,32",
            "addi a1,a1,-1",
            f"bnez a1,loop{idx}",
        ]
        data += [f"group{idx}:"]
        for row in rows:
            data += [
                ".dword "
                + ",".join("0x" + row["registers"][str(r)] for r in (5, 6, 7))
                + ",0x"
                + row["expected_rd"]
            ]
    # A real dependency chain: each instruction reads its predecessor's result.
    a = 0xDEADBEEF7FFFFFFF
    d = pack(0x60000000, 0, scale_only=True)
    code += [f"li t0,0x{a:016x}", f"li t2,0x{d:016x}"]
    for _ in range(64):
        a = oracle(a, d)
        code += [".insn r 0x0b,1,0,t0,t0,t2"]
    code += [
        f"li a2,0x{a:016x}",
        "bne t0,a2,fail",
        "li a0,0",
        "ret",
        "fail:",
        "li a0,1",
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
                ".globl tohost,fromhost",
                "tohost: .dword 0",
                "fromhost: .dword 0",
            ]
        )
        + "\n"
    )


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for v in ("ordinary", "profile"):
        build(v)
    cases = vectors()
    (OUTPUT / "vectors.json").write_text(
        json.dumps(
            {"contract_version": 1, "seed": "0x52455155414e54", "cases": cases},
            indent=2,
        )
        + "\n"
    )
    elf = fixtures.compile_asm("vectors", assembly(cases))
    rows = []
    for c in cases:
        if c["rd"]:
            rows.append(
                "{"
                + ",".join(
                    "0x" + x + "ull"
                    for x in (
                        c["registers"][str(c["rs1"])],
                        c["registers"][str(c["rs2"])],
                        c["expected_rd"],
                    )
                )
                + "}"
            )
    source = OUTPUT / "native.cc"
    source.write_text(
        '#include "kernels/xrequant/requant.h"\n#include "tensorflow/lite/kernels/internal/common.h"\nstatic const uint64_t rows[][3]={'
        + ",".join(rows)
        + "};\nint main(){for(const auto &r:rows){int64_t a; __builtin_memcpy(&a,&r[0],8); if(uint64_t(arch_project::xrequant(a,r[1]))!=r[2])return 1; uint32_t u=uint32_t(r[0]);int32_t x=u<0x80000000u?int32_t(u):-1-int32_t(~u);int m=uint32_t(r[1]),s=-int((r[1]>>32)&63); int64_t v=tflite::MultiplyByQuantizedMultiplier(x,m,s);if(!(r[1]&(1ull<<62))){int z=int8_t(r[1]>>38),lo=int8_t(r[1]>>46),hi=int8_t(r[1]>>54);v+=z;v=v<lo?lo:v>hi?hi:v;}if(uint64_t(v)!=r[2])return 2;}return 0;}\n"
    )
    upstream = ROOT / ".deps/tflite-micro"
    downloads = upstream / "tensorflow/lite/micro/tools/make/downloads"
    cxx = (
        "/Library/Developer/CommandLineTools/usr/bin/clang++"
        if sys.platform == "darwin"
        else "c++"
    )
    flags = (
        [
            "-isysroot",
            run(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).stdout.strip(),
        ]
        if sys.platform == "darwin"
        else []
    )
    command = [
        cxx,
        "-std=c++17",
        "-O1",
        "-DTF_LITE_STATIC_MEMORY",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        *flags,
    ]
    for inc in (
        ROOT,
        upstream,
        downloads / "gemmlowp",
        downloads / "ruy",
        downloads / "flatbuffers/include",
    ):
        command += ["-I", inc]
    run(
        [
            *command,
            source,
            upstream / "tensorflow/lite/kernels/internal/common.cc",
            "-o",
            OUTPUT / "native",
        ]
    )
    run([OUTPUT / "native"])
    nm = run([fixtures.PREFIX + "nm", "-n", elf]).stdout
    addr = lambda name: next(
        line.split()[0] for line in nm.splitlines() if line.endswith(" " + name)
    )
    config = OUTPUT / "regions.txt"
    config.write_text(
        f"code 0x{addr('_start')} 0x{addr('fixture_end')}\nregion invoke 0x{addr('invoke')}\n"
    )
    for v in ("ordinary", "profile"):
        run([*spike_command("X2", v), elf])
    for repeat in (1, 2):
        prefix = OUTPUT / f"profile{repeat}"
        run(
            [
                *spike_command("X2", "profile"),
                f"--profile-config={config}",
                f"--profile-output={prefix}",
                elf,
            ]
        )
        pcs = list(csv.DictReader(Path(str(prefix) + ".pcs.csv").open()))
        events = list(csv.DictReader(Path(str(prefix) + ".events.csv").open()))
        count = sum(
            int(r["count"]) for r in pcs if decode(int(r["bits"]), int(r["length"]))
        )
        if (
            count != len(cases) + 64
            or len(events) != 1
            or events[0]["complete"] != "1"
            or events[0]["status"] != "0"
        ):
            raise ValueError("incorrect ISA retirement/completion")
    for suffix in (".events.csv", ".pcs.csv"):
        if (OUTPUT / ("profile1" + suffix)).read_bytes() != (
            OUTPUT / ("profile2" + suffix)
        ).read_bytes():
            raise ValueError("ISA profiles differ")
    word = 0x100B | (5 << 7) | (6 << 15) | (7 << 20)
    invalid = [
        1 << 63,
        1 << 31,
        32 << 32,
        pack(1, 0, scale_only=True) | (1 << 38),
        pack(1, 0, 0, 1, 1) ^ (1 << 54),
    ]

    def trap_check(elf):
        for variant in ("ordinary", "profile"):
            run([*spike_command("X2", variant), elf])

    traps = 0
    for i, d in enumerate(invalid):
        text = fixtures.trap_fixture(word).replace(
            f".word {word}", f"li t1,1\nli t2,0x{d:x}\n.word {word}"
        )
        fixture = fixtures.compile_asm(f"invalid-{i}", text)
        trap_check(fixture)
        traps += 1
    # Parameter validation still happens when rd=x0.
    text = fixtures.trap_fixture(word & ~(31 << 7)).replace(
        f".word {word & ~(31 << 7)}", f"li t2,-1\n.word {word & ~(31 << 7)}"
    )
    trap_check(fixtures.compile_asm("invalid-x0", text))
    traps += 1
    for bit in (13, 14, *range(25, 32)):
        fixture = fixtures.compile_asm(
            f"encoding-{bit}", fixtures.trap_fixture(word ^ (1 << bit))
        )
        trap_check(fixture)
        traps += 1
    disabled = fixtures.compile_asm("disabled", fixtures.trap_fixture(word))
    rv32 = fixtures.compile_asm("rv32", fixtures.trap_fixture(word, True), True)
    for variant in ("ordinary", "profile"):
        run([*spike_command("X1", variant), disabled])
        binary = ROOT / (
            ".deps/spike/bin/spike"
            if variant == "ordinary"
            else ".deps/spike-profile/bin/spike"
        )
        library = ROOT / extension_identity(variant, "X2")["xrequant"]["library"]
        run([binary, f"--extlib={library}", "--isa=rv64imc", disabled])
        run([binary, f"--extlib={library}", "--isa=rv32imc_xrequant", rv32])
    traps += 3
    tiny = fixtures.compile_asm("disasm", assembly(cases[:1]))
    logged = run([*spike_command("X2"), "-l", tiny])
    if "xrequant" not in logged.stderr:
        raise ValueError("missing disassembly")
    # Exact decoder across every register field; funct3=0 remains legal Xqmac8.
    for rd in range(32):
        for a in range(32):
            for d in range(32):
                if not decode(0x100B | (rd << 7) | (a << 15) | (d << 20), 4):
                    raise ValueError("decode mismatch")
    result = {
        "status": "PASS",
        "vectors": len(cases),
        "random_vectors": 10000,
        "chain_length": 64,
        "profile_custom_retirements": len(cases) + 64,
        "repeat_profiles_identical": True,
        "trap_fixtures": traps,
        "native_asan_ubsan": True,
        "pinned_tflm_reference": True,
        "vectors_sha256": digest(OUTPUT / "vectors.json"),
        "elf_sha256": digest(elf),
        "extensions": {v: extension_identity(v, "X2") for v in ("ordinary", "profile")},
        "sources_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in (
                Path(__file__),
                ROOT / "tools/xrequant/contract.py",
                ROOT / "tools/xrequant/extension.cc",
                ROOT / "kernels/xrequant/requant.h",
            )
        },
    }
    (OUTPUT / "verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"Xrequant ISA: {len(cases)} oracle/reference vectors, 64-step chain, {traps} traps, repeat profiles and native sanitizers: PASS"
    )


if __name__ == "__main__":
    main()
