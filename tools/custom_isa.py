"""Configuration-aware extension selection; preserve existing X1 build identities."""

import json
from pathlib import Path

from tools.xqmac8.runtime import (
    digest,
)
from tools.xqmac8.runtime import (
    extension_identity as qmac_identity,
)
from tools.xqmac8.runtime import (
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
    if configuration == "X5":
        return extension_identity(variant, "X4")
    if configuration == "X4":
        record = json.loads((ROOT / f"build/xdwmac8/{variant}/build.json").read_text())
        for name, expected in record["inputs_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError(f"Xdwmac8 build input changed: {name}")
        if digest(ROOT / record["library"]) != record["library_sha256"]:
            raise ValueError("Xdwmac8 library changed")
        return {**extension_identity(variant, "X3"), "xdwmac8": record}
    if configuration == "X3":
        record = json.loads((ROOT / f"build/xpostinc/{variant}/build.json").read_text())
        for name, expected in record["inputs_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError(f"Xpostinc build input changed: {name}")
        if digest(ROOT / record["library"]) != record["library_sha256"]:
            raise ValueError("Xpostinc library changed")
        return {**extension_identity(variant, "X2"), "xpostinc": record}
    return (
        {"xqmac8": qmac_identity(variant), "xrequant": requant_identity(variant)}
        if configuration == "X2"
        else qmac_identity(variant)
    )


def spike_command(configuration, variant="ordinary"):
    if configuration == "X5":
        return spike_command("X4", variant)
    if configuration == "X4":
        base = spike_command("X3", variant)
        record = extension_identity(variant, "X4")["xdwmac8"]
        return [
            *base[:-1],
            f"--extlib={ROOT / record['library']}",
            "--isa=rv64imc_xqmac8_xrequant_xpostinc_xdwmac8",
        ]
    if configuration == "X3":
        base = spike_command("X2", variant)
        record = extension_identity(variant, "X3")["xpostinc"]
        return [
            *base[:-1],
            f"--extlib={ROOT / record['library']}",
            "--isa=rv64imc_xqmac8_xrequant_xpostinc",
        ]
    if configuration != "X2":
        return qmac_command(configuration, variant)
    base = qmac_command("X1", variant)
    return [
        *base[:-1],
        f"--extlib={ROOT / requant_identity(variant)['library']}",
        "--isa=rv64imc_xqmac8_xrequant",
    ]
