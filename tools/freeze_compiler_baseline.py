#!/usr/bin/env python3
"""Verify the recorded B0 files and preserve a content-checked, write-once archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tools/compiler/baseline.json"
sys.path.insert(0, str(ROOT / "tools"))

from profile_spike import check_output, load_capture, validate_elf


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_name(name: str) -> str:
    # TFLM recursively discovers this exact basename under EXTERNAL_DIR.
    # Even ignored backups must not register a second application target.
    return name + ".frozen" if Path(name).name == "Makefile_internal.inc" else name


def verify_files(root: Path, files: dict[str, str], *, archived: bool = False) -> None:
    for name, expected in files.items():
        path = root / (archive_name(name) if archived else name)
        if not path.is_file() or sha(path) != expected:
            raise ValueError(f"B0 file missing or changed: {path}")


def freeze(destination: Path) -> Path:
    contract = json.loads(CONTRACT.read_text())
    files = contract["frozen_files"]
    verify_files(ROOT, files)
    paths = contract["executables"]
    validate_elf(ROOT / paths["rv64"], ROOT / paths["profile"])
    capture = ROOT / "build/profiling/B0"
    manifest = json.loads((capture / "manifest.json").read_text())
    instructions = {int(key): value for key, value in manifest["instructions"].items()}
    for repeat in (1, 2):
        _, invoke, nodes, overhead = load_capture(
            capture / f"run{repeat}", manifest["nodes"], instructions
        )
        if (invoke["total"], len(nodes), overhead) != (4867278370, 64, 4820):
            raise ValueError("saved B0 instruction counts differ from the frozen reference")
        check_output((capture / f"run{repeat}-output.txt").read_text())
    check_output((capture / "ordinary-output.txt").read_text())
    for suffix in ("events.csv", "pcs.csv"):
        if (capture / f"run1.{suffix}").read_bytes() != (capture / f"run2.{suffix}").read_bytes():
            raise ValueError(f"B0 repeated captures differ: {suffix}")
    destination = destination.resolve()
    archive_manifest = {
        "schema_version": 1, "contract_sha256": sha(CONTRACT), "files": files,
        "archive_paths": {name: archive_name(name) for name in files},
    }
    if destination.exists():
        if json.loads((destination / "archive.json").read_text()) != archive_manifest:
            raise ValueError(f"refusing to overwrite a different B0 archive: {destination}")
        if sha(destination / "baseline.json") != sha(CONTRACT):
            raise ValueError(f"archived B0 contract changed: {destination / 'baseline.json'}")
        verify_files(destination, files, archived=True)
        print(f"B0 archive verified: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".B0-freeze-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "archive"
        staged.mkdir()
        for name in files:
            target = staged / archive_name(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        verify_files(staged, files, archived=True)
        (staged / "archive.json").write_text(json.dumps(archive_manifest, indent=2) + "\n")
        shutil.copy2(CONTRACT, staged / "baseline.json")
        staged.rename(destination)
    print(f"B0 archive frozen: {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/compiler/baseline/B0")
    args = parser.parse_args()
    try:
        freeze(args.output)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"B0 freeze failed: {error}\n")


if __name__ == "__main__":
    main()
