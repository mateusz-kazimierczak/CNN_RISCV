"""Configuration-aware extension selection; preserve existing X1 build identities."""

import json
from pathlib import Path
from tools.xqmac8.runtime import (
    digest,
    extension_identity as qmac_identity,
    spike_command as qmac_command,
)

ROOT = Path(__file__).resolve().parents[1]


def requant_identity(variant):
    record = json.loads((ROOT / f"build/xrequant/{variant}/build.json").read_text())
    for name, expected in record["inputs_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"Xrequant build input changed: {name}")
    if digest(ROOT / record["library"]) != record["library_sha256"]:
        raise ValueError("Xrequant library changed")
    return record


def extension_identity(variant, configuration="X1"):
    return (
        {"xqmac8": qmac_identity(variant), "xrequant": requant_identity(variant)}
        if configuration == "X2"
        else qmac_identity(variant)
    )


def spike_command(configuration, variant="ordinary"):
    if configuration != "X2":
        return qmac_command(configuration, variant)
    base = qmac_command("X1", variant)
    return [
        *base[:-1],
        f"--extlib={ROOT / requant_identity(variant)['library']}",
        "--isa=rv64imc_xqmac8_xrequant",
    ]
