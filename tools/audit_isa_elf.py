#!/usr/bin/env python3
"""Screen a linked ELF for floating-point, vector, and atomic instructions.

This checks static disassembly, not dynamic execution or software FP helpers.
It is not a complete decoder/validator for all possible RISC-V extensions.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.xpostinc.contract import decode as decode_postinc
from tools.xdwmac8.contract import decode as decode_dw
from tools.xqmac8.runtime import decode as decode_qmac8
from tools.xrequant.contract import decode as decode_requant


def capture(command: list[str]) -> str:
    return subprocess.run(command, check=True, text=True, capture_output=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("elf", type=Path)
    parser.add_argument("--readelf", required=True)
    parser.add_argument("--objdump", required=True)
    parser.add_argument(
        "--configuration",
        choices=("B0", "A0", "B1", "X1", "X2", "X3", "X4", "X5"),
        default="B0",
    )
    args = parser.parse_args()

    attributes = capture([args.readelf, "-h", "-A", str(args.elf)])
    architecture_match = re.search(r'Tag_RISCV_arch: "([^"]+)"', attributes)
    if not architecture_match:
        raise SystemExit("missing Tag_RISCV_arch")
    architecture = architecture_match.group(1)

    disassembly = capture([args.objdump, "-d", str(args.elf)])
    instruction_pattern = re.compile(
        r"^\s*[0-9a-f]+:\s+(?:[0-9a-f]{2,8}\s+)+([a-z][a-z0-9_.]*)",
        re.MULTILINE,
    )
    # Each entry is a static code location, regardless of how often it runs.
    mnemonics = instruction_pattern.findall(disassembly)
    forbidden = []
    custom = 0
    requant = 0
    postinc = 0
    dw = 0
    # Inspect raw bits as stock binutils emits custom opcodes as .4byte.
    for raw in re.findall(
        r"^\s*[0-9a-f]+:\s+([0-9a-f]{4}|[0-9a-f]{8})\s+", disassembly, re.MULTILINE
    ):
        bits = int(raw, 16)
        if len(raw) == 8 and bits & 0x7F in (0x0B, 0x2B, 0x5B, 0x7B):
            if args.configuration in ("X4", "X5") and decode_dw(bits, 4):
                dw += 1
            elif args.configuration in ("X3", "X4", "X5") and decode_postinc(bits, 4):
                if bits & 127 == 0x2B and (bits >> 7) & 31 == (bits >> 15) & 31 != 0:
                    forbidden.append(f"reserved Xpostinc load alias 0x{bits:08x}")
                postinc += 1
            elif args.configuration in ("X2", "X3", "X4", "X5") and decode_requant(
                bits, 4
            ):
                requant += 1
            elif args.configuration not in (
                "X1",
                "X2",
                "X3",
                "X4",
                "X5",
            ) or not decode_qmac8(bits, 4):
                forbidden.append(f"custom encoding 0x{bits:08x}")
            else:
                custom += 1
    for mnemonic in mnemonics:
        if (
            mnemonic.startswith(("amo", "lr.", "sc.", "v", "c.f"))
            or mnemonic.startswith("f")
            and not mnemonic.startswith("fence")
        ):
            forbidden.append(mnemonic)

    base_extensions = architecture.split("_")[0]
    unexpected_base = [
        extension for extension in "afdqv" if extension in base_extensions[5:]
    ]
    if unexpected_base or forbidden:
        raise SystemExit(
            "RV64IMC audit failed: "
            f"arch={architecture}, unexpected_base={unexpected_base}, "
            f"forbidden_instructions={sorted(set(forbidden))}"
        )

    if args.configuration in ("X4", "X5") and not dw:
        raise SystemExit("X4 contains no Xdwmac8 bank instructions")
    if args.configuration in ("X3", "X4", "X5") and not postinc:
        raise SystemExit("X3 ELF contains no Xpostinc instructions")
    if args.configuration in ("X2", "X3", "X4", "X5") and not requant:
        raise SystemExit("X2 ELF contains no Xrequant instructions")
    if args.configuration in ("X1", "X2", "X3", "X4", "X5") and not custom:
        raise SystemExit("X1 ELF contains no Xqmac8 instructions")
    print(
        "RV64IMC"
        + (
            "+Xqmac8+Xrequant+Xpostinc+Xdwmac8"
            if args.configuration in ("X4", "X5")
            else "+Xqmac8+Xrequant+Xpostinc"
            if args.configuration in ("X3", "X4", "X5")
            else "+Xqmac8+Xrequant"
            if args.configuration == "X2"
            else "+Xqmac8"
            if args.configuration == "X1"
            else ""
        )
        + " ELF audit: PASS"
    )
    print(f"architecture: {architecture}")
    print(f"decoded instruction count: {len(mnemonics)}")
    print("forbidden floating/vector/atomic instructions: 0")
    if args.configuration in ("X3", "X4", "X5"):
        print(f"Xpostinc static instruction locations: {postinc}")
    if args.configuration in ("X2", "X3", "X4", "X5"):
        print(f"Xrequant static instruction locations: {requant}")
    if args.configuration in ("X1", "X2", "X3", "X4", "X5"):
        print(f"Xqmac8 static instruction locations: {custom}")


if __name__ == "__main__":
    main()
