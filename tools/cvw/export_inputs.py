#!/usr/bin/env python3
"""Copy the accepted executable artifacts into a transferable simulation input set."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--b0",
        type=Path,
        default=ROOT
        / ".deps/tflite-micro/gen/rv64imc_rv64imc_release_with_logs_gcc/bin/efficientnet_lite0",
    )
    parser.add_argument(
        "--b1", type=Path, default=ROOT / "build/compiler/B1-spatial2-oc2/rv64/a0.elf"
    )
    parser.add_argument("--expected-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "build/cvw/inputs")
    args = parser.parse_args()
    contract = json.loads(Path(__file__).with_name("workloads.json").read_text())
    inputs = (
        (args.b0, "B0.elf", contract["B0"]["elf_sha256"]),
        (args.b1, "B1.elf", contract["B1"]["elf_sha256"]),
        (
            args.expected_output,
            "expected-output.bin",
            contract["expected_output_sha256"],
        ),
    )
    # Validate the complete set before writing any output.
    for path, name, expected in inputs:
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"not the accepted artifact: {name}")
    args.output.mkdir(parents=True, exist_ok=True)
    for path, name, expected in inputs:
        destination = args.output / name
        if path.resolve() != destination.resolve():
            shutil.copyfile(path, destination)
        print(name, expected)


if __name__ == "__main__":
    main()
