#!/usr/bin/env python3
"""Build Stage 2 helper/oracle tools, prepare parameters, and verify exact parity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compiler.frontend import import_model
from compiler.ir import REFERENCE_REVISION, ModelError
from compiler.quantization import compare_prepared, prepare_graph

WORK = ROOT / "build/compiler"
NATIVE = WORK / "numeric"
SOURCE = ROOT / ".deps/tflite-micro"
MODEL = ROOT / "models/efficientnet-lite0-int8.tflite"


def run(command, **kwargs):
    return subprocess.run(
        command, check=True, text=True, capture_output=True, **kwargs
    ).stdout.strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(jobs=8):
    if run(["git", "-C", str(SOURCE), "rev-parse", "HEAD"]) != REFERENCE_REVISION:
        raise ModelError("Stage 2 requires the pinned TFLM revision")
    if run(["git", "-C", str(SOURCE), "diff", "HEAD", "--"]):
        raise ModelError("Stage 2 requires unmodified TFLM sources")
    env = dict(os.environ)
    env["PATH"] = str(ROOT / ".deps/tflm-python/bin") + os.pathsep + env["PATH"]
    if shutil.which("xcrun"):
        env["SDKROOT"] = run(["xcrun", "--sdk", "macosx", "--show-sdk-path"])
    command = [
        "gmake",
        "--no-print-directory",
        "-s",
        f"-j{jobs}",
        "-C",
        str(SOURCE),
        "-f",
        "tensorflow/lite/micro/tools/make/Makefile",
        "-f",
        str(ROOT / "tools/compiler/prepared.mk"),
        f"EXTERNAL_DIR={ROOT}",
        f"BASE_GENDIR={WORK / 'tflm-oracle'}",
        "SKIP_DOWNLOADS=1",
        "BUILD_TYPE=release_with_logs",
        "WERROR=1",
    ]
    run([*command, "compiler_prepared_oracle"], env=env)
    gendir = Path(run([*command, "list_gendir"], env=env))
    oracle = gendir / "bin/compiler_prepared_oracle"
    library = gendir / "lib/libtensorflow-microlite.a"
    downloads = SOURCE / "tensorflow/lite/micro/tools/make/downloads"
    includes = [
        SOURCE,
        downloads / "gemmlowp",
        downloads / "flatbuffers/include",
        downloads / "ruy",
    ]
    flags = [
        "g++",
        "-std=c++17",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wno-unused-parameter",
        "-DTF_LITE_STATIC_MEMORY",
        "-DTF_LITE_DISABLE_X86_NEON",
    ]
    for directory in includes:
        flags.extend(["-I", str(directory)])
    sources = [
        str(ROOT / "kernels/reference/numerics.cc"),
        str(SOURCE / "tensorflow/lite/kernels/internal/common.cc"),
    ]
    NATIVE.mkdir(parents=True, exist_ok=True)
    shared = NATIVE / (
        "libnumerics.dylib" if sys.platform == "darwin" else "libnumerics.so"
    )
    shared_command = [
        *flags,
        "-dynamiclib" if sys.platform == "darwin" else "-shared",
        "-fPIC",
        *sources,
        str(library),
        "-o",
        str(shared),
    ]
    run(shared_command, env=env)
    sanitized = NATIVE / "numeric-sanitized"
    # The system CLT sanitizer runtime follows macOS more closely than an older
    # selected Xcode installation. Keep B0/oracle on their pinned build flags.
    clt = Path("/Library/Developer/CommandLineTools/usr/bin/clang++")
    sanitizer_cxx = os.environ.get(
        "COMPILER_SANITIZER_CXX",
        str(clt) if sys.platform == "darwin" and clt.exists() else "g++",
    )
    sanitized_command = [
        sanitizer_cxx,
        *flags[1:],
        "-g",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        *sources,
        str(ROOT / "tests/compiler/numerics_main.cc"),
        str(library),
        "-o",
        str(sanitized),
    ]
    run(sanitized_command, env=env)
    flags_text = run(
        [
            *command,
            "-f",
            str(ROOT / "tools/spike_profile/print_flags.mk"),
            "profile-print-flags",
        ],
        env=env,
    )
    names = (
        "tools/compiler/prepared.cc",
        "tools/compiler/prepared.mk",
        "tools/prepare_compiler.py",
        "kernels/reference/numerics.cc",
        "kernels/reference/numerics.h",
        "tests/compiler/numerics_main.cc",
        "compiler/quantization.py",
        "compiler/frontend.py",
        "compiler/validation.py",
        "compiler/ir.py",
        "tests/compiler/test_quantization.py",
        "tools/compiler/requirements.txt",
    )
    # Include all transitive upstream sources/headers used by numeric wrappers.
    upstream = [
        "tensorflow/lite/kernels/internal/common.cc",
        "tensorflow/lite/kernels/internal/common.h",
        "tensorflow/lite/kernels/internal/quantization_util.cc",
        "tensorflow/lite/kernels/kernel_util.cc",
    ]
    upstream += [
        str(p.relative_to(SOURCE))
        for p in sorted((SOURCE / "tensorflow/lite/micro/kernels").glob("*_common.cc"))
    ]
    upstream += [
        str(p.relative_to(SOURCE))
        for p in sorted(
            (SOURCE / "tensorflow/lite/kernels/internal/reference").rglob("*.h")
        )
    ]
    upstream += [
        str(p.relative_to(SOURCE))
        for p in sorted((downloads / "gemmlowp/fixedpoint").glob("*.h"))
    ]
    record = {
        "schema_version": 1,
        "tflm_revision": REFERENCE_REVISION,
        "repository_revision": run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]),
        "repository_dirty_status": run(
            ["git", "-C", str(ROOT), "status", "--porcelain"]
        ),
        "native_compiler": run(["g++", "--version"]).splitlines()[0],
        "sanitizer_compiler": run([sanitizer_cxx, "--version"]).splitlines()[0],
        "oracle": str(oracle.relative_to(ROOT)),
        "oracle_sha256": sha(oracle),
        "library_sha256": sha(library),
        "shared": str(shared.relative_to(ROOT)),
        "shared_sha256": sha(shared),
        "sanitized": str(sanitized.relative_to(ROOT)),
        "sanitized_sha256": sha(sanitized),
        "oracle_command": [*command, "compiler_prepared_oracle"],
        "resolved_oracle_flags": flags_text.splitlines(),
        "shared_command": shared_command,
        "sanitized_command": sanitized_command,
        "source_sha256": {name: sha(ROOT / name) for name in names},
        "upstream_source_sha256": {name: sha(SOURCE / name) for name in upstream},
    }
    (NATIVE / "build.json").write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n"
    )
    return record


def verify_build(record):
    for name, digest in record["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ModelError(f"Stage 2 source changed since build: {name}")
    for name, digest in record["upstream_source_sha256"].items():
        if sha(SOURCE / name) != digest:
            raise ModelError(f"Stage 2 upstream source changed since build: {name}")
    for key in ("oracle", "shared", "sanitized"):
        if sha(ROOT / record[key]) != record[f"{key}_sha256"]:
            raise ModelError(f"Stage 2 {key} binary changed since build")


def capture_parameters(model: Path, output: Path, record: dict) -> list[dict]:
    # import_model performs strict validation before the native tool sees data.
    graph = import_model(model)
    prepared = prepare_graph(graph)
    verify_build(record)
    output.mkdir(parents=True, exist_ok=True)
    raw = output / "oracle-raw.json"
    run([str(ROOT / record["oracle"]), str(model.resolve()), str(raw)])
    records = json.loads(raw.read_text())
    for row in records:
        if row["integers"].pop("_end") != 0:
            raise ModelError("invalid oracle record sentinel")
    count = compare_prepared(prepared, records)
    artifacts = {
        "prepared_ir.json": prepared.to_json(),
        "oracle.json": json.dumps(records, sort_keys=True, indent=2) + "\n",
    }
    manifest = {
        "schema_version": 1,
        "stage": 2,
        "model_sha256": graph.model_sha256,
        "graph_ir_sha256": graph.sha256,
        "prepared_ir_sha256": prepared.sha256,
        "prepared_parameter_parity": "PASS",
        "nodes": len(records),
        "compared_integer_values": count,
        "provenance": record,
        "passes": [
            "stage1_validation",
            "offline_integer_preparation",
            "accumulator_range_proof",
            "unpadded_1x1_adjusted_bias_proof",
            "pinned_prepare_elementwise_parity",
        ],
        "capabilities": {
            "prepared_parameters": True,
            "memory_plan": False,
            "inference_codegen": False,
        },
        "artifacts": {
            name: hashlib.sha256(text.encode()).hexdigest()
            for name, text in artifacts.items()
        },
    }
    for name, text in artifacts.items():
        (output / name).write_text(text)
    (output / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "prepare", "sanitize"))
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--output-dir", type=Path, default=WORK / "prepared")
    args = parser.parse_args()
    try:
        if args.command == "build":
            if args.jobs < 1:
                raise ModelError("jobs must be positive")
            build(args.jobs)
            print("Stage 2 native tools built")
        else:
            record = json.loads((NATIVE / "build.json").read_text())
            verify_build(record)
            if args.command == "prepare":
                rows = capture_parameters(args.model, args.output_dir, record)
                print(f"Prepared parameter parity: PASS ({len(rows)} nodes)")
            else:
                print(run([str(ROOT / record["sanitized"])], timeout=30))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stdout, error.stderr, file=sys.stderr)
        parser.exit(1, f"Stage 2 {args.command} failed: {error}\n")


if __name__ == "__main__":
    main()
