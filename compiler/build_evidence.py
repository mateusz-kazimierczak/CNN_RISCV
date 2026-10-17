"""Portable, content-addressed build snapshots; readers never consult live sources."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def local_file(root, name):
    path = root / name
    if Path(name).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"unsafe evidence path: {name}")
    return path


def snapshot_build(output, generated, record, root, dependencies):
    """Freeze bytes verified against compile-time dependency and generation hashes."""
    generation = json.loads((generated / "manifest.json").read_text())
    if digest(generated / "manifest.json") != record["generation_manifest_sha256"]:
        raise ValueError("generation manifest changed during build")
    paths = {name: root / name for name in dependencies}
    expected = dict(dependencies)
    for name, sha in record["source_sha256"].items():
        paths[name], expected[name] = root / name, sha
    for name, sha in generation["source_sha256"].items():
        paths[name], expected[name] = root / name, sha
    artifacts = {}
    for name, sha in generation["artifacts"].items():
        path = generated / name
        key = (
            str(path.resolve().relative_to(root))
            if path.resolve().is_relative_to(root)
            else str(path.resolve())
        )
        paths[key], expected[key], artifacts[name] = path, sha, key
    for path in (
        generated / "manifest.json",
        output / ("a0.elf" if record["kind"] == "rv64" else "a0"),
        root / "tools/build_a0.py",
    ):
        key = (
            str(path.resolve().relative_to(root))
            if path.resolve().is_relative_to(root)
            else str(path.resolve())
        )
        paths[key], expected[key] = path, digest(path)
    if (
        expected[record["binary"]] != record["binary_sha256"]
        or expected["tools/build_a0.py"] != record["driver_sha256"]
    ):
        raise ValueError("build changed before snapshot")
    objects = {}
    for name, path in paths.items():
        if digest(path) != expected[name]:
            raise ValueError(f"build input changed before snapshot: {name}")
        objects[name] = {
            "sha256": expected[name],
            "size": path.stat().st_size,
            "blob": "files/" + expected[name],
        }
    manifest = {
        "schema_version": 2,
        "build": record,
        "generation": generation,
        "artifacts": artifacts,
        "files": objects,
        "source_snapshot_status": "verified build-time bytes",
    }
    content = canonical(manifest).encode()
    identity = hashlib.sha256(content).hexdigest()
    parent = output / "evidence"
    parent.mkdir(exist_ok=True)
    destination = parent / identity
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=parent) as temporary:
            staged = Path(temporary) / "snapshot"
            (staged / "files").mkdir(parents=True)
            for name, obj in objects.items():
                target = staged / obj["blob"]
                if not target.exists():
                    shutil.copyfile(paths[name], target)
                if digest(target) != obj["sha256"]:
                    raise ValueError("snapshot changed while copying")
            (staged / "manifest.json").write_bytes(content)
            staged.rename(destination)
    verify_snapshot(destination / "manifest.json", identity)
    return {"manifest": f"evidence/{identity}/manifest.json", "sha256": identity}


def verify_snapshot(path, expected_sha=None):
    path = Path(path)
    if expected_sha is not None and digest(path) != expected_sha:
        raise ValueError("build evidence manifest hash mismatch")
    data = json.loads(path.read_text())
    if data.get("schema_version") != 2:
        raise ValueError("unsupported build evidence schema")
    for name, obj in data["files"].items():
        blob = local_file(path.parent, obj["blob"])
        if (
            obj["blob"] != "files/" + obj["sha256"]
            or blob.stat().st_size != obj["size"]
            or digest(blob) != obj["sha256"]
        ):
            raise ValueError(f"snapshot bytes changed: {name}")
    for mapping in (
        data["build"]["dependency_sha256"],
        data["build"]["source_sha256"],
        data["generation"]["source_sha256"],
    ):
        for name, sha in mapping.items():
            if data["files"][name]["sha256"] != sha:
                raise ValueError("snapshot build/source identity mismatch")
    generation_objects = [
        obj
        for obj in data["files"].values()
        if obj["sha256"] == data["build"]["generation_manifest_sha256"]
    ]
    if (
        not generation_objects
        or json.loads(
            local_file(path.parent, generation_objects[0]["blob"]).read_text()
        )
        != data["generation"]
    ):
        raise ValueError("snapshot generation manifest mismatch")
    binary = data["files"][data["build"]["binary"]]
    if binary["sha256"] != data["build"]["binary_sha256"]:
        raise ValueError("snapshot binary identity mismatch")
    for name, sha in data["generation"]["artifacts"].items():
        if data["files"][data["artifacts"][name]]["sha256"] != sha:
            raise ValueError("snapshot generation identity mismatch")
    return data


def open_build(path):
    path = Path(path)
    record = json.loads(path.read_text())
    reference = record["evidence"]
    snapshot = local_file(path.parent, reference["manifest"])
    data = verify_snapshot(snapshot, reference["sha256"])
    if {k: v for k, v in record.items() if k != "evidence"} != data["build"]:
        raise ValueError("build record disagrees with immutable evidence")
    return snapshot, data


def artifact_path(snapshot, data, name):
    key = data["artifacts"][name]
    return local_file(Path(snapshot).parent, data["files"][key]["blob"])
