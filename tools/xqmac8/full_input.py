#!/usr/bin/env python3
"""Verify a second full RV64 input using unchanged X1 production kernel objects.

Only the target harness seed changes; the canonical performance ELF is preserved.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.build_a0 import verify_build
from tools.xqmac8.runtime import digest
from tools.custom_isa import spike_command, extension_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generated-dir", type=Path, default=ROOT / "build/compiler/X1"
    )
    args = parser.parse_args()
    directory = args.generated_dir.resolve()
    production = verify_build(directory, "rv64")
    if production["configuration"] not in ("X1", "X2"):
        raise ValueError("requires an X1/X2 production build")
    for name, expected_hash in production["link_inputs_sha256"].items():
        if digest(ROOT / name) != expected_hash:
            raise ValueError(
                f"production link input changed: {name}; rebuild the production target"
            )
    output = (
        ROOT
        / "build/xqmac8"
        / (
            "full-random_42"
            if directory == ROOT / "build/compiler/X1"
            else directory.name + "/full-random_42"
        )
    )
    output.mkdir(parents=True, exist_ok=True)
    original = ROOT / "tools/compiler/a0_target.cc"
    text = original.read_text()
    if text.count("a0_fill_input(1);") != 1:
        raise ValueError("target harness seed site changed")
    source = output / "a0_target.cc"
    source.write_text(text.replace("a0_fill_input(1);", "a0_fill_input(42);"))
    compile_command = next(
        c
        for c in production["commands"]
        if "-c" in c and c[c.index("-c") + 1] == str(original)
    )
    old_object = compile_command[compile_command.index("-o") + 1]
    obj = output / "a0_target.o"
    compile_command = [
        str(source)
        if v == str(original)
        else str(obj)
        if v == old_object
        else str(output / "target.d")
        if v.endswith("/" + Path(old_object).stem + ".d")
        else v
        for v in compile_command
    ]
    subprocess.run(compile_command, check=True)
    elf = output / "inference.elf"
    command = list(production["commands"][-1])
    command = [
        str(obj)
        if v == old_object
        else f"-Wl,-Map,{output / 'inference.map'}"
        if v.startswith("-Wl,-Map,")
        else v
        for v in command
    ]
    command[command.index("-o") + 1] = str(elf)
    subprocess.run(command, check=True)
    execution = [*spike_command(production["configuration"]), str(elf)]
    result = subprocess.run(
        execution, check=True, capture_output=True, text=True, timeout=600
    )
    (output / "stdout.txt").write_text(result.stdout)
    (output / "stderr.txt").write_text(result.stderr)
    oracle = Path(
        json.loads((ROOT / "build/compiler/oracle/latest.json").read_text())["capture"]
    )
    expected = (oracle / "random_42/output.bin").read_bytes()
    match = re.search(r"^output_hex=([0-9a-f]{2000})$", result.stdout, re.MULTILINE)
    if not match or bytes.fromhex(match.group(1)) != expected:
        raise ValueError("random_42 full RV64 output differs from oracle")
    # Bind all reused production objects as well as the replacement harness.
    report = {
        "status": "PASS",
        "case": "random_42",
        "seed": 42,
        "full_output_bytes_compared": 1000,
        "production_build_manifest_sha256": digest(directory / "rv64/build.json"),
        "production_binary_sha256": production["binary_sha256"],
        "source_sha256": digest(source),
        "binary_sha256": digest(elf),
        "output_sha256": hashlib.sha256(expected).hexdigest(),
        "reused_objects_sha256": {p: digest(p) for p in command if p.endswith(".o")},
        "commands": [compile_command, command, execution],
        "extension": extension_identity("ordinary", production["configuration"]),
    }
    (output / "verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"{production['configuration']} random_42 full RV64 inference: PASS (1000 output bytes)"
    )


if __name__ == "__main__":
    main()
