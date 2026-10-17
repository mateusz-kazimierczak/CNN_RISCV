"""Frozen workspaces and sealed investigation artifacts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from compiler.build_evidence import canonical, digest, local_file, verify_snapshot

ROOT = Path(__file__).resolve().parents[2]
TOOLCHAIN = ROOT / ".deps/xpack-riscv/bin/riscv-none-elf-"


def run(command, **kwargs):
    return subprocess.run(
        [str(x) for x in command], check=True, capture_output=True, text=True, **kwargs
    )


def materialize(snapshot, data, directory):
    """Original names are metadata; only confined relative paths are restored."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, obj in data["files"].items():
        target = local_file(directory, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_file(snapshot.parent, obj["blob"]), target)
    script = "tflm/platform/rv64imc/link.ld"
    if script not in data["files"]:
        # Checkpoint-1 records predate linker-input capture. Recover this exact
        # pinned script from Stage 0, never from an unverified current source.
        baseline = ROOT / "build/compiler/baseline/B0"
        contract = json.loads((baseline / "baseline.json").read_text())
        source = baseline / script
        if digest(source) != contract["frozen_files"][script]:
            raise ValueError("frozen linker-script provenance unavailable")
        target = local_file(directory, script)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        (directory.parent / "supplemental-linker-input.json").write_text(
            canonical(
                {
                    "file": script,
                    "sha256": digest(source),
                    "source": "Stage 0 frozen B0 archive; loaded-image equality required",
                    "baseline_contract_sha256": digest(baseline / "baseline.json"),
                }
            )
        )


def original_root(data):
    binary = data["build"]["binary"]
    command = data["build"]["commands"][-1]
    output = command[command.index("-o") + 1]
    if Path(binary).is_absolute() or not output.endswith("/" + binary):
        raise ValueError("investigation requires a repository-relative RV64 build")
    return output[: -(len(binary) + 1)]


def rewrite_command(command, original, workspace):
    # Each command element is an argv value, never shell text.
    return [
        arg.replace(original + "/", str(workspace) + "/") if i else arg
        for i, arg in enumerate(command)
    ]


def verify_toolchain(data):
    compiler = Path(data["build"]["commands"][0][0])
    if digest(compiler) != data["build"]["compiler_binary_sha256"]:
        raise ValueError("compiler binary differs from measured build")
    # Default search directories and libraries still belong to the installed
    # pinned toolchain. Verify the recorded default headers before using it.
    for name, sha in data["build"]["dependency_sha256"].items():
        if name.startswith(".deps/xpack-riscv/") and digest(ROOT / name) != sha:
            raise ValueError("installed toolchain dependency changed")
    return str(compiler)


def seal(directory, destination_root, format_name, metadata):
    inventory = {
        str(p.relative_to(directory)): {"sha256": digest(p), "size": p.stat().st_size}
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "schema_version": 2,
        "format": format_name,
        **metadata,
        "files": inventory,
    }
    (directory / "manifest.json").write_text(canonical(manifest))
    identity = digest(directory / "manifest.json")
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / identity
    if destination.exists():
        verify_archive(destination, format_name)
    else:
        directory.rename(destination)
    with tempfile.NamedTemporaryFile(
        "w", prefix=".latest-", dir=destination_root, delete=False
    ) as pointer:
        pointer.write(canonical({"artifact_id": identity}))
        pointer_path = Path(pointer.name)
    pointer_path.replace(destination_root / "latest.json")
    return destination


def archive_path(path):
    path = Path(path).resolve()
    if path.name == "latest.json":
        identity = json.loads(path.read_text())["artifact_id"]
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("unsafe investigation pointer")
        return path.parent / identity
    return path.parent if path.name == "manifest.json" else path


def verify_archive(path, format_name):
    path = archive_path(path)
    data = json.loads((path / "manifest.json").read_text())
    if (
        data.get("schema_version") != 2
        or data.get("format") != format_name
        or digest(path / "manifest.json") != path.name
    ):
        raise ValueError("invalid investigation archive identity/schema")
    names = {str(p.relative_to(path)) for p in path.rglob("*") if p.is_file()} - {
        "manifest.json"
    }
    if names != set(data["files"]):
        raise ValueError("investigation inventory mismatch")
    for name, obj in data["files"].items():
        item = local_file(path, name)
        if item.stat().st_size != obj["size"] or digest(item) != obj["sha256"]:
            raise ValueError(f"investigation artifact changed: {name}")
    if "build_evidence_sha256" in data:
        verify_snapshot(
            path / "build_evidence/manifest.json", data["build_evidence_sha256"]
        )
    return path, data
