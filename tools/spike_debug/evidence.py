"""Bounded v2 bundle validation and execution schedules for live simulation."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import PurePosixPath

from tools.profile_spike import (
    CLASSIFICATION,
    capture,
    disassemble,
    tool,
    unique_symbol,
)

MAX = 2**64 - 1


def uint(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"0|[1-9][0-9]{0,19}", value)
        or int(value) > MAX
    ):
        raise ValueError("Invalid unsigned evidence counter/address")
    return int(value)


def safe_path(name):
    return (
        isinstance(name, str)
        and bool(name)
        and not PurePosixPath(name).is_absolute()
        and not any(p in ("", ".", "..") for p in name.split("/"))
        and not any(c in name for c in ("\\", "\0"))
        and not re.match(r"^[a-z]:", name, re.IGNORECASE)
    )


def read_bundle(path):
    if path.stat().st_size > 256 * 1024**2:
        raise ValueError("Bundle exceeds compressed limit")
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        names = [e.filename for e in entries]
        if (
            len(names) > 10000
            or len(set(names)) != len(names)
            or not all(map(safe_path, names))
            or any(
                e.file_size > 128 * 1024**2 or e.compress_type not in (0, 8)
                for e in entries
            )
            or sum(e.file_size for e in entries) > 512 * 1024**2
        ):
            raise ValueError("Unsafe, duplicate or oversized bundle entries")
        m = json.loads(z.read("manifest.json"))
        if (
            not isinstance(m, dict)
            or m.get("format") != "riscv-execution-explorer"
            or m.get("schemaVersion") != 2
        ):
            raise ValueError("Unsupported bundle: regenerate schema v2 evidence")
        if set(m["files"]) != set(names) - {"manifest.json"}:
            raise ValueError("Invalid bundle inventory")
        for name, meta in m["files"].items():
            digest, size = hashlib.sha256(), 0
            with z.open(name) as source:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > 128 * 1024**2:
                        raise ValueError("Bundle entry exceeds decompressed limit")
                    digest.update(chunk)
            if size != meta["size"] or digest.hexdigest() != meta["sha256"]:
                raise ValueError("Bundle integrity failure")
        data = json.loads(z.read("evidence.json"))
    if not isinstance(data, dict) or data.get("schemaVersion") != 2:
        raise ValueError("Unsupported evidence schema")
    return data


def execution_schedule(data, elf, syms):
    """Return ordered observed stages, never manufacture eliminated-node events."""
    nodes, units, events = (
        data["graph"]["nodes"],
        data["executionPlan"]["units"],
        data["events"],
    )
    nids = {n["id"] for n in nodes}
    if (
        len(nids) != len(nodes)
        or len({u["id"] for u in units}) != len(units)
        or len({e["id"] for e in events}) != len(events)
    ):
        raise ValueError("Duplicate graph, execution-unit or event identity")
    adapter = data["provenance"].get("captureAdapter")
    if adapter not in ("compiler-v2", "litert"):
        raise ValueError("Unsupported execution adapter")
    # The label is not an ISA/backend selector. Verify the actual linked code.
    attributes = capture(tool("readelf"), "-A", str(elf))
    arch = re.search(r'Tag_RISCV_arch: "([^"]+)"', attributes)
    allowed = {"i", "m", "c", "zicsr", "zifencei", "zmmul", "zca"}
    if (
        not arch
        or not arch[1].startswith("rv64")
        or any(re.sub(r"[0-9].*", "", p) not in allowed for p in arch[1][4:].split("_"))
    ):
        raise ValueError("Live debugger requires an RV64IMC executable")
    code = disassemble(elf)
    instructions = data["instructions"]
    if set(map(str, code)) != set(instructions):
        raise ValueError("Bundle disassembly does not match ELF")
    for pc, i in instructions.items():
        actual = code[uint(pc)]
        if (int(i["bits"], 16), i["length"], i["mnemonic"], i["operands"]) != (
            actual["bits"],
            actual["length"],
            actual["mnemonic"],
            actual["operands"],
        ):
            raise ValueError("Bundle instruction differs from ELF")
    by_id = {e["id"]: e for e in events}
    roots = [e for e in events if e["scope"] == "inference"]
    setup = [e for e in events if e["scope"] == "setup"]
    overhead = [e for e in events if e["scope"] == "invocation-overhead"]
    if len(roots) != 1 or len(setup) > 1 or len(overhead) != 1 or not units:
        raise ValueError("Invalid invocation/setup scopes or empty schedule")
    claimed, stages = set(), []
    for order, u in enumerate(units):
        if (
            u["order"] != order
            or not re.fullmatch(r"[A-Za-z0-9:._/-]{1,256}", u["id"])
            or not u["nodes"]
            or len(set(u["nodes"])) != len(u["nodes"])
            or not set(u["nodes"]) <= nids
            or not u["eventIds"]
        ):
            raise ValueError("Invalid or unobserved execution unit")
        # An execution unit may have several observations (e.g. a shared call).
        # Each gets a distinct live schedule position and conditioned breakpoint.
        for eid in u["eventIds"]:
            e = by_id.get(eid)
            if (
                eid in claimed
                or not e
                or e["scope"] != "execution-unit"
                or e["unitId"] != u["id"]
            ):
                raise ValueError("Invalid execution event relationship")
            claimed.add(eid)
            entry = uint(e["entry"])
            if adapter == "compiler-v2" and unique_symbol(syms, u["symbol"]) != entry:
                raise ValueError("Execution symbol/entry differs from linked ELF")
            stages.append(
                {
                    "id": u["id"],
                    "eventId": eid,
                    "nodes": u["nodes"],
                    "entry": entry,
                    "label": u["symbol"],
                    "index": len(stages),
                }
            )
    if claimed != {e["id"] for e in events if e["scope"] == "execution-unit"}:
        raise ValueError("Unexpected execution events")
    positions = {e["id"]: i for i, e in enumerate(events)}
    stages.sort(key=lambda s: positions[s["eventId"]])
    for index, stage in enumerate(stages):
        stage["index"] = index
    for n in nodes:
        expected = [u["id"] for u in units if n["id"] in u["nodes"]]
        if (
            n["unitIds"] != expected
            or n["disposition"] not in ("executed", "eliminated")
            or (n["disposition"] == "eliminated") != (not expected)
        ):
            raise ValueError("Graph origins disagree with execution plan")
    partition = {}
    for e in events:
        if e["scope"] not in (
            "inference",
            "setup",
            "execution-unit",
            "invocation-overhead",
        ):
            raise ValueError("Unexpected measurement scope")
        if e["scope"] != "invocation-overhead" and (
            e.get("complete") is not True
            or e.get("status") != "0"
            or str(uint(e["entry"])) not in instructions
            or str(uint(e["returnPc"])) not in instructions
        ):
            raise ValueError("Incomplete, failed or invalid measurement boundary")
        total = 0
        for pc, count in e["counts"].items():
            value = uint(count)
            if pc not in instructions or (
                value and instructions[pc]["mnemonic"] not in CLASSIFICATION
            ):
                raise ValueError("Unknown executed instruction")
            total += value
            if e["scope"] in ("execution-unit", "invocation-overhead"):
                partition[pc] = partition.get(pc, 0) + value
        if total != uint(e["total"]):
            raise ValueError("Nonconserving event counts")
    root = roots[0]
    for pc in set(partition) | set(root["counts"]):
        if partition.get(pc, 0) != uint(root["counts"].get(pc, "0")):
            raise ValueError("Execution counts do not conserve per PC")
    totals = data["totals"]
    if totals != {
        "inference": root["total"],
        "overhead": overhead[0]["total"],
        "allocation": setup[0]["total"] if setup else None,
    }:
        raise ValueError("Model totals disagree with measurement scopes")
    root_entry = uint(root["entry"])
    if not any(s["kind"] in "tTW" and s["address"] == root_entry for s in syms):
        raise ValueError("Invocation entry is not an ELF symbol")
    return adapter, root_entry, uint(setup[0]["entry"]) if setup else None, stages
