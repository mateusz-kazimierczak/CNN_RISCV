#!/usr/bin/env python3
"""Reject instructions outside the RV64IMC baseline in a linked ELF."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def capture(command: list[str]) -> str:
    return subprocess.run(command, check=True, text=True, capture_output=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("elf", type=Path)
    parser.add_argument("--readelf", required=True)
    parser.add_argument("--objdump", required=True)
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
    mnemonics = instruction_pattern.findall(disassembly)
    forbidden = []
    for mnemonic in mnemonics:
        if (
            mnemonic.startswith(("amo", "lr.", "sc.", "v"))
            or (mnemonic.startswith("f") and not mnemonic.startswith("fence"))
            or mnemonic.startswith("c.f")
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

    print("RV64IMC ELF audit: PASS")
    print(f"architecture: {architecture}")
    print(f"decoded instruction count: {len(mnemonics)}")
    print("forbidden floating/vector/atomic instructions: 0")


if __name__ == "__main__":
    main()
