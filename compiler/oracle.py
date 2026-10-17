"""Integrity and byte-level comparison of captured TFLM tensors, without an IR."""

from __future__ import annotations

import hashlib
import json
import math
import signal
from pathlib import Path

from .reference_inputs import CASES, INPUT_BYTES, fnv1a


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(root: Path, name: str) -> Path:
    path = root / name
    if Path(name).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"artifact escapes capture directory: {name}")
    return path


def verify_capture(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("schema_version") != 1 or manifest.get("configuration") != "TFLM_ORACLE":
        raise ValueError("unsupported oracle manifest")
    if [case["name"] for case in manifest["cases"]] != [case.name for case in CASES]:
        raise ValueError("capture must contain the complete ordered Stage 0 input suite")
    for expected, case in zip(CASES, manifest["cases"]):
        root = directory / case["name"]
        for name, digest in case["files"].items():
            path = artifact(root, name)
            if not path.is_file() or sha(path) != digest:
                raise ValueError(f"{case['name']}: missing or changed artifact {name}")
        input_data = (root / "input.bin").read_bytes()
        if len(input_data) != INPUT_BYTES or input_data != expected.data():
            raise ValueError(f"{case['name']}: input differs from the specified generator")
        if case["expected_signal"] != expected.expected_signal or case["expected_nodes"] != expected.expected_nodes:
            raise ValueError(f"{case['name']}: reference outcome contract changed")
        if expected.expected_signal is None:
            output_data = (root / "output.bin").read_bytes()
            if case["returncode"] != 0 or len(output_data) != 1000 or fnv1a(output_data) != case["output_fnv1a"]:
                raise ValueError(f"{case['name']}: invalid public output")
        else:
            if case["returncode"] != -int(signal.SIGABRT) or case["output_fnv1a"] is not None or (root / "output.bin").exists():
                raise ValueError(f"{case['name']}: expected an explicit reference SIGABRT without output")
        tensors = case["tensors"]
        if [tensor["node"] for tensor in tensors] != list(range(expected.expected_nodes)):
            raise ValueError(f"{case['name']}: incomplete or reordered node output sequence")
        if len({tensor["tensor"] for tensor in tensors}) != expected.expected_nodes:
            raise ValueError(f"{case['name']}: duplicate graph tensor IDs")
        identity = ("node", "tensor", "slot", "operator", "type", "shape", "bytes")
        for tensor, first in zip(tensors, manifest["cases"][0]["tensors"]):
            if any(tensor[key] != first[key] for key in identity):
                raise ValueError(f"{case['name']}: graph tensor metadata differs from baseline")
        for tensor in tensors:
            path = artifact(root, tensor["file"])
            if tensor["type"] not in ("INT8", "UINT8") or tensor["slot"] != 0:
                raise ValueError(f"unsupported oracle output contract: {tensor}")
            if (not tensor["shape"] or any(dim <= 0 for dim in tensor["shape"]) or
                    math.prod(tensor["shape"]) != tensor["bytes"] or
                    path.stat().st_size != tensor["bytes"] or
                    sha(path) != tensor["sha256"] or
                    case["files"].get(tensor["file"]) != tensor["sha256"]):
                raise ValueError(f"{case['name']}: invalid tensor at node {tensor['node']}")
        if expected.expected_signal is None:
            if (tensors[0]["tensor"], tensors[-1]["tensor"]) != (0, 165):
                raise ValueError("UINT8 boundary conversions must remain in the graph")
            if (root / tensors[-1]["file"]).read_bytes() != output_data:
                raise ValueError(f"{case['name']}: final node differs from public output")
    if manifest["cases"][0]["output_fnv1a"] != "0x4b6a91e2":
        raise ValueError("baseline checksum differs from B0")
    return manifest


def golden_record(manifest: dict) -> dict:
    """Compact tracked hashes; full arrays remain retrievable in ignored captures."""
    return {
        "schema_version": 1,
        "model_sha256": manifest["provenance"]["model_sha256"],
        "tflm_revision": manifest["provenance"]["tflm_revision"],
        "node_outputs": [
            {key: value for key, value in tensor.items() if key not in ("file", "sha256")}
            for tensor in manifest["cases"][0]["tensors"]
        ],
        "cases": [
            {
                "name": case["name"],
                "pattern": case["pattern"],
                "seed": case["seed"],
                "expected_nodes": case["expected_nodes"],
                "expected_signal": case["expected_signal"],
                "returncode": case["returncode"],
                "input_sha256": case["files"]["input.bin"],
                "output_sha256": case["files"].get("output.bin"),
                "output_fnv1a": case["output_fnv1a"],
                "tensor_sha256": [tensor["sha256"] for tensor in case["tensors"]],
            }
            for case in manifest["cases"]
        ],
    }


def verify_golden(directory: Path, golden: Path) -> dict:
    manifest = verify_capture(directory)
    expected = json.loads(golden.read_text())
    actual = golden_record(manifest)
    if actual != expected:
        for old, new in zip(expected["cases"], actual["cases"]):
            for node, (a, b) in enumerate(zip(old["tensor_sha256"], new["tensor_sha256"])):
                if a != b:
                    raise ValueError(f"golden mismatch: input {new['name']}, first divergent node {node}")
        raise ValueError("oracle metadata or public input/output differs from golden fixtures")
    return manifest


def compare_captures(reference: Path, candidate: Path) -> None:
    """Compare actual arrays and report the first divergent node and byte."""
    left, right = verify_capture(reference), verify_capture(candidate)
    if left["provenance"]["model_sha256"] != right["provenance"]["model_sha256"]:
        raise ValueError("cannot compare captures from different models")
    for a, b in zip(left["cases"], right["cases"]):
        for expected, actual in zip(a["tensors"], b["tensors"]):
            identity = ("node", "tensor", "slot", "operator", "type", "shape", "bytes")
            if any(expected[key] != actual[key] for key in identity):
                raise ValueError(f"{a['name']}: tensor metadata differs at node {expected['node']}")
            x = (reference / a["name"] / expected["file"]).read_bytes()
            y = (candidate / b["name"] / actual["file"]).read_bytes()
            if x != y:
                offset = next(index for index, (u, v) in enumerate(zip(x, y)) if u != v)
                raise ValueError(
                    f"{a['name']}: first divergent node {expected['node']}, "
                    f"tensor {expected['tensor']}, byte {offset}: {x[offset]} != {y[offset]}"
                )
