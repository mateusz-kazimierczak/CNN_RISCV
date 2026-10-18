"""Select and authenticate a Spike extension built for the exact simulator ABI."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATCH, MASK = 0x0000000B, 0xFE00707F


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extension_identity(variant):
    record_path = ROOT / "build/xqmac8" / variant / "build.json"
    record = json.loads(record_path.read_text())
    for name, expected in record["inputs_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError(
                f"Xqmac8 {variant} build input changed: {name}; rebuild extension"
            )
    if digest(ROOT / record["library"]) != record["library_sha256"]:
        raise ValueError("Xqmac8 extension library changed")
    return record


def spike_command(configuration, variant="ordinary"):
    simulator = ROOT / (
        ".deps/spike/bin/spike"
        if variant == "ordinary"
        else ".deps/spike-profile/bin/spike"
    )
    if configuration != "X1":
        return [str(simulator), "--isa=rv64imc"]
    record = extension_identity(variant)
    return [
        str(simulator),
        f"--extlib={ROOT / record['library']}",
        "--isa=rv64imc_xqmac8",
    ]


def decode(bits, length):
    return length == 4 and bits & MASK == MATCH
