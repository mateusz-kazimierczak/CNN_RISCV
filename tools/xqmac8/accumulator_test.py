#!/usr/bin/env python3
"""Check wide register storage against the Python ISA oracle and scalar schedules."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.xqmac8.runtime import digest, extension_identity, spike_command
from tools.xqmac8.vectors import vectors

OUTPUT = ROOT / "build/xqmac8/acc64-tests"


def run(command):
    result = subprocess.run(
        list(map(str, command)), text=True, capture_output=True, timeout=120
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command}\n{result.stdout}{result.stderr}"
        )
    return result


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows, chain = [], []
    for case in vectors():
        if not case["rd"]:
            continue
        regs = case["registers"]
        row = (
            regs[str(case["rd"])],
            regs[str(case["rs1"])],
            regs[str(case["rs2"])],
            case["expected_rd"],
        )
        rows.append("{" + ",".join("0x" + x + "ull" for x in row) + "}")
        if case["name"] == "accumulation-chain":
            chain.append(row)
    source = OUTPUT / "main.cc"
    source.write_text(
        '#include "tests/compiler/accumulator_register_main.cc"\n'
        + "static const uint64_t rows[][4] = {"
        + ",".join(rows)
        + "};\n"
        + "__attribute__((noinline)) int64_t chain(int64_t acc) {\n"
        + "\n".join(
            f"acc = arch_project::xqmac8_register(acc,0x{r[1]}ull,0x{r[2]}ull);"
            for r in chain
        )
        + "\nreturn acc; }\nint main() {\n"
        + "for (const auto &r : rows) { int64_t acc; __builtin_memcpy(&acc,&r[0],8); "
        + "if (uint64_t(arch_project::xqmac8_register(acc,r[1],r[2])) != r[3]) return 1; }\n"
        + f"if (uint64_t(chain(0x{chain[0][0]}ull)) != 0x{chain[-1][3]}ull) return 2;\n"
        + "return check_all_schedules() ? 0 : 3; }\n"
    )
    cxx = (
        "/Library/Developer/CommandLineTools/usr/bin/clang++"
        if sys.platform == "darwin"
        else "c++"
    )
    sdk = (
        [
            "-isysroot",
            run(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).stdout.strip(),
        ]
        if sys.platform == "darwin"
        else []
    )
    commands = [
        [
            cxx,
            "-std=c++17",
            "-O1",
            "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all",
            *sdk,
            "-I",
            ROOT,
            source,
            "-o",
            OUTPUT / "native",
        ]
    ]
    run(commands[-1])
    run([OUTPUT / "native"])
    start = OUTPUT / "start.S"
    start.write_text(""".section .text.init
.globl _start
_start:
  .option push
  .option norelax
  la gp, __global_pointer$
  .option pop
  la sp, __stack_top
  call main
  slli a0, a0, 1
  addi a0, a0, 1
  la a1, tohost
  sd a0, 0(a1)
1: j 1b
.section .tohost,"aw",@progbits
.balign 64
.globl tohost, fromhost
tohost: .dword 0
fromhost: .dword 0
""")
    elf = OUTPUT / "tests.elf"
    commands.append(
        [
            ROOT / ".deps/xpack-riscv/bin/riscv-none-elf-g++",
            "-std=c++17",
            "-O2",
            "-g",
            "-march=rv64imc",
            "-mabi=lp64",
            "-mcmodel=medany",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-exceptions",
            "-fno-rtti",
            "-nostdlib",
            "-nostartfiles",
            "-I",
            ROOT,
            source,
            start,
            "-Wl,--no-relax",
            "-T",
            ROOT / "tflm/platform/rv64imc/link.ld",
            "-o",
            elf,
        ]
    )
    run(commands[-1])
    for variant in ("ordinary", "profile"):
        command = [*spike_command("X1", variant), elf]
        commands.append(command)
        run(command)
    result = {
        "status": "PASS",
        "vectors": len(rows),
        "seed": "0x514d414338",
        "chain_length": len(chain),
        "schedule_fixtures": 72,
        "schedule_shapes": [
            [1, 8, 1],
            [1, 16, 4],
            [2, 8, 4],
            [3, 24, 8],
            [4, 32, 6],
            [49, 320, 4],
        ],
        "native_asan_ubsan": True,
        "ordinary_spike": True,
        "profile_spike": True,
        "elf_sha256": digest(elf),
        "source_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in (
                source,
                Path(__file__),
                ROOT / "tests/compiler/accumulator_register_main.cc",
                ROOT / "kernels/xqmac8/dot8.h",
                ROOT / "kernels/rv64imc/pointwise.h",
            )
        },
        "extensions": {v: extension_identity(v) for v in ("ordinary", "profile")},
        "commands": [[str(x) for x in c] for c in commands],
    }
    (OUTPUT / "verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"Accumulator registers: {len(rows)} oracle vectors, 64-step chain, 72 schedule fixtures; native sanitizers and both Spike variants: PASS"
    )


if __name__ == "__main__":
    main()
