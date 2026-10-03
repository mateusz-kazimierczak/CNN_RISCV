#!/usr/bin/env python3
"""Embed model bytes in an aligned C++ array for the TFLM application.

The generated source includes model_data.h; the FlatBuffer graph is preserved
for the target interpreter to read, rather than converted into kernel code.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def validate_symbol(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise argparse.ArgumentTypeError(f"invalid C++ symbol: {value}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--header", required=True, type=Path)
    parser.add_argument("--symbol", required=True, type=validate_symbol)
    args = parser.parse_args()

    data = args.input.read_bytes()
    args.source.parent.mkdir(parents=True, exist_ok=True)
    args.header.parent.mkdir(parents=True, exist_ok=True)

    guard = f"{args.symbol.upper()}_H_"
    args.header.write_text(
        "// Generated file; do not edit.\n"
        f"#ifndef {guard}\n"
        f"#define {guard}\n\n"
        "#include <cstddef>\n"
        "#include <cstdint>\n\n"
        f"extern const unsigned char {args.symbol}[];\n"
        f"inline constexpr std::size_t {args.symbol}_size = {len(data)};\n\n"
        f"#endif  // {guard}\n",
        encoding="utf-8",
    )

    with args.source.open("w", encoding="utf-8") as output:
        output.write("// Generated file; do not edit.\n")
        output.write('#include "model_data.h"\n\n')
        output.write(f"alignas(16) const unsigned char {args.symbol}[] = {{\n")
        for offset in range(0, len(data), 16):
            chunk = data[offset : offset + 16]
            output.write("  ")
            output.write(", ".join(f"0x{byte:02x}" for byte in chunk))
            output.write(",\n")
        output.write("};\n")


if __name__ == "__main__":
    main()
