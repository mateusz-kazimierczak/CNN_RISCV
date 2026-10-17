#!/usr/bin/env python3
"""Build an isolated native TFLM oracle and capture/verify full node tensors."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compiler.oracle import compare_captures, sha, verify_capture, verify_golden
from compiler.reference_inputs import CASES, fnv1a

WORK = ROOT / "build/compiler"
BUILD_RECORD = WORK / "oracle-build.json"
GOLDEN = ROOT / "tests/compiler/fixtures/oracle-golden.json"
CONTRACT = ROOT / "tools/compiler/baseline.json"


def run(command: list[str], **kwargs) -> str:
    result = subprocess.run(command, check=True, text=True, capture_output=True, **kwargs)
    return result.stdout


def build(jobs: int) -> dict:
    contract = json.loads(CONTRACT.read_text())
    source = ROOT / ".deps/tflite-micro"
    if not (source / ".git").exists():
        raise ValueError("TFLM is unavailable; run gmake run-native first")
    revision = run(["git", "-C", str(source), "rev-parse", "HEAD"]).strip()
    if revision != contract["tflm_revision"]:
        raise ValueError(f"TFLM revision mismatch: {revision}")
    if run(["git", "-C", str(source), "diff", "HEAD", "--"]):
        raise ValueError("TFLM tracked sources are modified; oracle requires the pinned reference")
    if sha(ROOT / "models/efficientnet-lite0-int8.tflite") != contract["model_sha256"]:
        raise ValueError("model differs from frozen B0")
    env = dict(os.environ)
    env["PATH"] = str(ROOT / ".deps/tflm-python/bin") + os.pathsep + env["PATH"]
    if shutil.which("xcrun"):
        env["SDKROOT"] = run(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).strip()
    command = [
        "gmake", "--no-print-directory", "-s", f"-j{jobs}", "-C", str(source),
        "-f", "tensorflow/lite/micro/tools/make/Makefile",
        "-f", str(ROOT / "tools/compiler/oracle.mk"),
        f"EXTERNAL_DIR={ROOT}", f"BASE_GENDIR={WORK / 'tflm-oracle'}",
        "SKIP_DOWNLOADS=1", "BUILD_TYPE=release_with_logs", "WERROR=1",
    ]
    # Use upstream's compilation flags and source selection, with separate objects/library.
    subprocess.run([*command, "compiler_tflm_oracle"], check=True, env=env)
    gendir = Path(run([*command, "list_gendir"], env=env).strip())
    binary = gendir / "bin/compiler_tflm_oracle"
    flags = run([
        *command, "-f", str(ROOT / "tools/spike_profile/print_flags.mk"),
        "profile-print-flags",
    ], env=env)
    record = {
        "schema_version": 1,
        "binary": str(binary.relative_to(ROOT)),
        "binary_sha256": sha(binary),
        "library_sha256": sha(gendir / "lib/libtensorflow-microlite.a"),
        "tflm_revision": revision,
        "model_sha256": contract["model_sha256"],
        "repository_revision": run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).strip(),
        "repository_dirty_status": run(["git", "-C", str(ROOT), "status", "--porcelain"]),
        "native_compiler": run(["g++", "--version"]).splitlines()[0],
        "command": [*command, "compiler_tflm_oracle"],
        "resolved_flags": flags.strip().splitlines(),
        "source_sha256": {
            name: sha(ROOT / name) for name in (
                "tools/compiler/oracle.cc", "tools/compiler/oracle.mk",
                "tools/capture_tflm_oracle.py", "compiler/reference_inputs.py",
                "compiler/oracle.py", "tflm/generated/model_data.cc",
                "tflm/generated/model_data.h",
            )
        },
    }
    WORK.mkdir(parents=True, exist_ok=True)
    BUILD_RECORD.write_text(json.dumps(record, indent=2) + "\n")
    print(f"Native oracle built: {binary}")
    return record


def parse_table(directory: Path) -> list[dict]:
    with (directory / "tensors.tsv").open() as table:
        records = list(csv.DictReader(table, delimiter="\t"))
    tensors = []
    for record in records:
        tensor = {
            key: int(record[key]) for key in ("node", "tensor", "slot", "bytes")
        }
        tensor.update({key: record[key] for key in ("operator", "type", "file")})
        tensor["shape"] = [int(dim) for dim in record["shape"].split(",")]
        tensor["sha256"] = sha(directory / tensor["file"])
        tensors.append(tensor)
    return tensors


def capture(output: Path, record: dict, *, reuse: bool = True) -> Path:
    binary = ROOT / record["binary"]
    if sha(binary) != record["binary_sha256"]:
        raise ValueError("oracle binary changed since build; rebuild the oracle")
    for name, digest in record["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f"oracle source changed since build: {name}; rebuild the oracle")
    # Provenance changes produce a new capture; old full tensor arrays remain available.
    identity = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    destination = output.resolve() / identity[:16]
    if destination.exists():
        if not reuse:
            raise ValueError(f"repeat capture needs a different output directory: {destination}")
        manifest = verify_capture(destination)
        if manifest["provenance"] != record:
            raise ValueError(f"capture provenance conflict: {destination}")
    else:
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".oracle-", dir=output) as temporary:
            staged = Path(temporary) / "capture"
            staged.mkdir()
            cases = []
            for case in CASES:
                directory = staged / case.name
                directory.mkdir()
                expected = case.data()
                requested = directory / "requested_input.bin"
                requested.write_bytes(expected)
                command = [str(binary), "-" if case.name == "baseline" else str(requested), str(directory)]
                result = subprocess.run(command, check=False, text=True, capture_output=True)
                (directory / "stdout.txt").write_text(result.stdout)
                (directory / "stderr.txt").write_text(result.stderr)
                expected_returncode = -int(getattr(signal, case.expected_signal)) if case.expected_signal else 0
                if result.returncode != expected_returncode:
                    raise ValueError(
                        f"{case.name}: native oracle returned {result.returncode}, expected "
                        f"{expected_returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
                    )
                if (directory / "input.bin").read_bytes() != expected:
                    raise ValueError(f"native input differs from Python generator: {case.name}")
                requested.unlink()
                cases.append({
                    **asdict(case),
                    "returncode": result.returncode,
                    "output_fnv1a": fnv1a((directory / "output.bin").read_bytes()) if not case.expected_signal else None,
                    "tensors": parse_table(directory),
                    "files": {p.name: sha(p) for p in sorted(directory.iterdir())},
                })
                outcome = f"; known reference {case.expected_signal} at node {case.expected_nodes}" if case.expected_signal else ""
                print(f"Captured {case.name}: {case.expected_nodes} complete node tensors{outcome}", flush=True)
            manifest = {
                "schema_version": 1,
                "configuration": "TFLM_ORACLE",
                "provenance": record,
                "capabilities": {
                    "full_output_arrays": True, "full_node_arrays": True,
                    "capture_at_node_completion": True, "preserve_all_tensors": True,
                    "prepared_parameters": False, "performance_measurement": False,
                },
                "cases": cases,
            }
            (staged / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            verify_capture(staged)
            if GOLDEN.exists():
                verify_golden(staged, GOLDEN)
            staged.rename(destination)
    if GOLDEN.exists():
        verify_golden(destination, GOLDEN)
    (output / "latest.json").write_text(json.dumps({"capture": str(destination)}) + "\n")
    print(f"Oracle capture verified: {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--jobs", type=int, default=8)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--output", type=Path, default=WORK / "oracle")
    for name in ("verify", "compare"):
        command = commands.add_parser(name)
        command.add_argument("reference", type=Path)
        if name == "compare":
            command.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            if args.jobs < 1:
                raise ValueError("jobs must be positive")
            build(args.jobs)
        elif args.command == "capture":
            capture(args.output, json.loads(BUILD_RECORD.read_text()))
        elif args.command == "verify":
            verify_golden(args.reference, GOLDEN)
            print("Complete oracle capture matches golden fixtures: PASS")
        else:
            compare_captures(args.reference, args.candidate)
            print("All node tensor arrays match byte-for-byte: PASS")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stdout:
            print(error.stdout, file=sys.stderr)
        parser.exit(1, f"Oracle {args.command} failed: {error}\n")


if __name__ == "__main__":
    main()
