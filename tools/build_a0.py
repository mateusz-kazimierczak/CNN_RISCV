#!/usr/bin/env python3
"""Build generated A0/B1 programs; verify native arrays and RV64 output."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compiler.build_evidence import snapshot_build
from compiler.ir import REFERENCE_REVISION, ModelError
from compiler.oracle import verify_golden
from compiler.reference_inputs import CASES

WORK = ROOT / "build/compiler"
GENERATED = WORK / "A0"
UPSTREAM = ROOT / ".deps/tflite-micro"
TOOLCHAIN = ROOT / ".deps/xpack-riscv/bin/riscv-none-elf-"


def run(command, **kwargs):
    return subprocess.run(
        [str(x) for x in command], check=True, text=True, capture_output=True, **kwargs
    ).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recorded_path(path):
    path = path.resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def verify_generation(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    if (manifest["configuration"], manifest["stage"]) not in (
        ("A0", 4),
        ("B1", 5),
        ("B1", 6),
    ):
        raise ModelError("build requires implemented A0 or B1 generation")
    for name, digest in manifest["artifacts"].items():
        if sha(directory / name) != digest:
            raise ModelError(f"generated artifact changed: {name}")
    for name, digest in manifest["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ModelError(f"generator/runtime source changed: {name}; regenerate")
    if manifest.get("runtime") == "standalone":
        plan = json.loads((directory / "kernel_plan.json").read_text())
        if any(
            not n["implementation"].startswith(("project/", "rv64imc/"))
            for n in plan["nodes"]
        ):
            raise ModelError("standalone target contains a reference fallback")
        return manifest
    if run(
        ["git", "-C", UPSTREAM, "rev-parse", "HEAD"]
    ).strip() != REFERENCE_REVISION or run(
        ["git", "-C", UPSTREAM, "diff", "HEAD", "--"]
    ):
        raise ModelError("A0 requires unmodified pinned TFLM sources")
    return manifest


def build(directory, kind):
    generated = verify_generation(directory)
    output = directory / kind
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if sys.platform == "darwin":
        env["SDKROOT"] = run(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).strip()
    compiler = "g++"
    if kind == "sanitized":
        compiler = os.environ.get(
            "COMPILER_SANITIZER_CXX",
            "/Library/Developer/CommandLineTools/usr/bin/clang++"
            if sys.platform == "darwin"
            else "g++",
        )
    if kind == "rv64":
        compiler = str(TOOLCHAIN) + "g++"
    flags = [
        "-std=c++17",
        "-O2",
        "-g",
        "-ffunction-sections",
        "-fdata-sections",
        "-fno-exceptions",
        "-fno-rtti",
        "-fno-threadsafe-statics",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-Wno-unused-parameter",
        "-DTF_LITE_STATIC_MEMORY",
        "-DTF_LITE_DISABLE_X86_NEON",
        "-fstack-usage",
    ]
    flags += (
        ["-DA0_CAPTURE=1"]
        if kind in ("capture", "sanitized")
        else ["-DA0_CAPTURE=0", "-DNDEBUG"]
    )
    if kind == "sanitized":
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    if kind == "rv64":
        flags += [
            "-march=rv64imc",
            "-mabi=lp64",
            "-mcmodel=medany",
            "-fno-builtin",
            "-fno-use-cxa-atexit",
        ]
    if generated["configuration"] == "B1":
        flags += ['-DCOMPILER_CONFIGURATION="B1"', "-I", str(ROOT)]
    standalone = generated.get("runtime") == "standalone"
    downloads = UPSTREAM / "tensorflow/lite/micro/tools/make/downloads"
    for include in (
        (directory, ROOT, ROOT / "kernels/project")
        if standalone
        else (
            directory,
            ROOT / "kernels/reference",
            UPSTREAM,
            downloads / "gemmlowp",
            downloads / "ruy",
            downloads / "flatbuffers/include",
        )
    ):
        flags += ["-I", str(include)]
    sources = [
        directory / "constants.cc",
        directory / "model.cc",
        ROOT / "kernels/reference/numerics.cc",
        UPSTREAM / "tensorflow/lite/kernels/internal/common.cc",
    ]
    if standalone:
        sources = [
            directory / "constants.cc",
            directory / "model.cc",
            ROOT / "kernels/project/softmax.cc",
        ]
        flags = [f for f in flags if not f.startswith("-DTF_")]
    if generated.get("runtime", "reference") != "reference":
        sources.append(ROOT / "kernels/project/quantization.cc")
    sources += (
        [
            ROOT / "tools/compiler/a0_target.cc",
            ROOT / "tflm/platform/rv64imc/syscalls.cc",
            ROOT / "tflm/platform/rv64imc/crt0.S",
        ]
        if kind == "rv64"
        else [ROOT / "tools/compiler/a0_host.cc"]
    )
    commands = []
    objects = []
    dependencies = {}
    for i, source in enumerate(sources):
        obj = output / f"{i}_{source.stem}.o"
        # Discover with the same flags, then verify the actual compiler depfile
        # and all bytes again. This includes system headers and assembler input.
        deptext = run([compiler, *flags, "-M", "-MT", "unit", str(source)], env=env)
        names = shlex.split(deptext.replace("\\\n", "").split(":", 1)[1])
        before = {recorded_path(Path(p)): sha(Path(p)) for p in names}
        depfile = obj.with_suffix(".d")
        command = [
            compiler,
            *flags,
            "-MD",
            "-MF",
            str(depfile),
            "-c",
            str(source),
            "-o",
            str(obj),
        ]
        run(command, env=env)
        actual = shlex.split(depfile.read_text().replace("\\\n", "").split(":", 1)[1])
        after = {recorded_path(Path(p)): sha(Path(p)) for p in actual}
        if before != after or any(
            k in dependencies and dependencies[k] != v for k, v in after.items()
        ):
            raise ModelError("compiler dependencies changed during compilation")
        dependencies.update(after)
        commands.append(command)
        objects.append(obj)
    binary = output / ("a0.elf" if kind == "rv64" else "a0")
    link_flags = []
    if kind == "rv64":
        link_flags = [
            "-nostartfiles",
            "-static",
            "-Wl,--gc-sections",
            f"-Wl,-T,{ROOT / 'tflm/platform/rv64imc/link.ld'}",
            f"-Wl,-Map,{output / 'a0.map'}",
        ]
    elif sys.platform == "darwin":
        link_flags = ["-Wl,-dead_strip"]
    link_inputs = {}
    if kind == "rv64":
        paths = [*objects, ROOT / "tflm/platform/rv64imc/link.ld"]
        paths += [
            Path(run([compiler, *flags, f"-print-file-name={name}"]).strip())
            for name in ("libstdc++.a", "libm.a", "libgcc.a", "libc.a", "libgloss.a")
        ]
        link_inputs = {recorded_path(p): sha(p) for p in paths}
    command = [compiler, *flags, *map(str, objects), *link_flags, "-o", str(binary)]
    run(command, env=env)
    if any(sha(ROOT / name) != h for name, h in link_inputs.items()):
        raise ModelError("link input changed during linking")
    if kind == "rv64":
        loaded = {
            recorded_path(Path(line[5:]))
            for line in (output / "a0.map").read_text().splitlines()
            if line.startswith("LOAD ")
        }
        if not loaded <= set(link_inputs):
            raise ModelError("unrecorded linker input")
        dependencies.update(link_inputs)
    commands.append(command)
    nm = str(TOOLCHAIN) + "nm" if kind == "rv64" else "nm"
    symbols = run(
        [nm, binary]
        if sys.platform == "darwin" and kind != "rv64"
        else [nm, "-C", binary]
    )
    (output / "symbols.txt").write_text(symbols)
    if any(
        token in symbols
        for token in (
            "MicroInterpreter",
            "MicroAllocator",
            "AllocateTensors",
            "flatbuffers::",
            "operator new" if kind == "rv64" else "__no_heap_token__",
        )
    ):
        raise ModelError("A0 linked forbidden interpreter/allocator symbols")
    nodes = sorted(set(re.findall(r"(?<![A-Za-z0-9])_?(a0_node_\d\d)\b", symbols)))
    if len(nodes) != 64:
        raise ModelError(f"expected 64 stable node symbols, got {len(nodes)}")
    audit = None
    if kind == "rv64":
        audit = run(
            [
                sys.executable,
                ROOT / "tools/audit_rv64_elf.py",
                "--readelf",
                str(TOOLCHAIN) + "readelf",
                "--objdump",
                str(TOOLCHAIN) + "objdump",
                binary,
            ]
        )
        (output / "isa-audit.txt").write_text(audit)
        for forbidden in (" malloc", " calloc", " realloc", " _sbrk", "_Zn"):
            if any(forbidden in line for line in symbols.splitlines()):
                raise ModelError(f"RV64 A0 contains heap symbol: {forbidden}")
        (output / "sections.txt").write_text(
            run([str(TOOLCHAIN) + "size", "-A", binary])
        )
        (output / "elf-headers.txt").write_text(
            run([str(TOOLCHAIN) + "readelf", "-h", "-A", "-l", "-S", binary])
        )
    section_sizes = {}
    allocated_span = None
    if kind == "rv64":
        triples = re.findall(
            r"^(\.[^\s]+)\s+(\d+)\s+(\d+)\s*$",
            (output / "sections.txt").read_text(),
            re.MULTILINE,
        )
        section_sizes = {
            name: int(size) for name, size, addr in triples if int(addr) > 0
        }
        addresses = [
            (int(addr), int(addr) + int(size))
            for name, size, addr in triples
            if int(addr) > 0
        ]
        allocated_span = max(end for start, end in addresses) - min(
            start for start, end in addresses
        )
    stack_frames = []
    for path in sorted(output.glob("*.su")):
        for line in path.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                stack_frames.append(
                    {"function": parts[0], "bytes": int(parts[1]), "kind": parts[2]}
                )
    (output / "stack-frames.json").write_text(
        json.dumps(
            {
                "frames": stack_frames,
                "maximum_individual_frame_bytes": max(
                    (f["bytes"] for f in stack_frames), default=0
                ),
                "scope": "per-function compiler reports, may include linker-discarded functions; not a total call-chain peak",
            },
            indent=2,
        )
        + "\n"
    )
    record = {
        "schema_version": 1,
        "configuration": generated["configuration"],
        "kind": kind,
        "binary": recorded_path(binary),
        "binary_sha256": sha(binary),
        "generation_manifest_sha256": sha(directory / "manifest.json"),
        "compiler": run([compiler, "--version"]).splitlines()[0],
        "compiler_binary_sha256": sha(Path(shutil.which(compiler))),
        "dependency_sha256": dependencies,
        "link_inputs_sha256": link_inputs,
        "commands": commands,
        "environment": {"SDKROOT": env.get("SDKROOT")},
        "stable_node_symbols": nodes,
        "isa_audit": audit,
        "interpreter_linked": False,
        "section_sizes": section_sizes,
        "static_allocated_address_span_bytes": allocated_span,
        "source_sha256": {
            recorded_path(p): sha(p)
            for p in [
                *sources,
                ROOT / "tools/build_a0.py",
                ROOT / "compiler/build_evidence.py",
            ]
        },
        "workload": {
            "case": "baseline",
            "seed": 1,
            "sha256": hashlib.sha256(CASES[0].data()).hexdigest(),
        }
        if kind == "rv64"
        else None,
        "driver_sha256": sha(ROOT / "tools/build_a0.py"),
        "runtime_headers_sha256": {
            str(p.relative_to(UPSTREAM)): sha(p)
            for p in (
                []
                if standalone
                else sorted(
                    (UPSTREAM / "tensorflow/lite/kernels/internal").rglob("*.h")
                )
            )
        },
        "external_headers_sha256": {
            str(p.relative_to(UPSTREAM)): sha(p)
            for p in (
                []
                if standalone
                else sorted((downloads / "gemmlowp/fixedpoint").glob("*.h"))
            )
        },
        "model_sha256": generated["model_sha256"],
    }
    if standalone and any(".deps/tflite-micro" in name for name in dependencies):
        raise ModelError("standalone compilation used a forbidden TFLM dependency")
    record["evidence"] = snapshot_build(output, directory, record, ROOT, dependencies)
    (output / "build.json").write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n"
    )
    print(f"{generated['configuration']} {kind} built: {binary}", flush=True)
    return record


def verify_build(directory, kind):
    verify_generation(directory)
    record = json.loads((directory / kind / "build.json").read_text())
    if (
        sha(directory / "manifest.json") != record["generation_manifest_sha256"]
        or sha(ROOT / record["binary"]) != record["binary_sha256"]
    ):
        raise ModelError("A0 build provenance changed; rebuild")
    for name, digest in record["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ModelError(f"A0 build source changed: {name}")
    if record["driver_sha256"] != sha(ROOT / "tools/build_a0.py"):
        raise ModelError("A0 build driver changed; rebuild")
    for name, digest in record["runtime_headers_sha256"].items():
        if sha(UPSTREAM / name) != digest:
            raise ModelError(f"pinned arithmetic header changed: {name}")
    for name, digest in record["external_headers_sha256"].items():
        if sha(UPSTREAM / name) != digest:
            raise ModelError(f"pinned fixed-point dependency changed: {name}")
    return record


def compare_case(reference, candidate, case, *, captured=True):
    expected_status = 2 if case["expected_signal"] else 0
    result = json.loads((candidate / "result.json").read_text())
    if (
        result["status"] != expected_status
        or not result["guards"]
        or result["output_available"] != (expected_status == 0)
    ):
        raise ModelError(
            f"{case['name']}: wrong A0 status/guards/output state: {result}"
        )
    if result["failed_node"] != (62 if expected_status else -1):
        raise ModelError(f"{case['name']}: wrong failing node")
    count = 0
    if captured:
        with (candidate / "tensors.tsv").open() as file:
            rows = list(csv.DictReader(file, delimiter="\t"))
        if (
            result["captured_nodes"] != case["expected_nodes"]
            or len(rows) != case["expected_nodes"]
        ):
            raise ModelError(f"{case['name']}: incomplete node arrays")
        for expected, actual in zip(case["tensors"], rows):
            if (
                int(actual["node"]),
                int(actual["tensor"]),
                int(actual["bytes"]),
                actual["file"],
            ) != (
                expected["node"],
                expected["tensor"],
                expected["bytes"],
                expected["file"],
            ):
                raise ModelError(f"{case['name']}: node identity/extent changed")
            a = (reference / expected["file"]).read_bytes()
            b = (candidate / actual["file"]).read_bytes()
            if a != b:
                byte = next(
                    (i for i, (x, y) in enumerate(zip(a, b)) if x != y),
                    min(len(a), len(b)),
                )
                raise ModelError(
                    f"{case['name']}: first divergent node {expected['node']}, tensor {expected['tensor']}, byte {byte}"
                )
            count += 1
    if expected_status:
        if (candidate / "output.bin").exists():
            raise ModelError("failed reference domain must not expose a final output")
    elif (reference / "output.bin").read_bytes() != (
        candidate / "output.bin"
    ).read_bytes():
        raise ModelError(f"{case['name']}: public output differs")
    return count


def differential(directory, kind):
    record = verify_build(directory, kind)
    oracle = Path(json.loads((WORK / "oracle/latest.json").read_text())["capture"])
    reference = verify_golden(
        oracle, ROOT / "tests/compiler/fixtures/oracle-golden.json"
    )
    output = directory / kind / "captures"
    output.mkdir(exist_ok=True)
    results = []
    for case in reference["cases"]:
        dest = output / case["name"]
        dest.mkdir(exist_ok=True)
        if (dest / "output.bin").exists():
            (dest / "output.bin").unlink()
        command = [ROOT / record["binary"], oracle / case["name"] / "input.bin", dest]
        executed = subprocess.run(
            list(map(str, command)),
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        (dest / "stdout.txt").write_text(executed.stdout)
        (dest / "stderr.txt").write_text(executed.stderr)
        expected_status = 2 if case["expected_signal"] else 0
        if executed.returncode != expected_status or executed.stderr:
            raise ModelError(
                f"A0 {kind} {case['name']} failed: return={executed.returncode}\n{executed.stderr}"
            )
        nodes = compare_case(
            oracle / case["name"], dest, case, captured=kind != "native"
        )
        results.append(
            {
                "name": case["name"],
                "nodes_compared": nodes,
                "status": expected_status,
                "files": {p.name: sha(p) for p in sorted(dest.iterdir())},
            }
        )
        print(
            f"{record['configuration']} {kind} {case['name']}: PASS ({nodes} full node arrays, status {expected_status})",
            flush=True,
        )
    report = {
        "status": "PASS",
        "configuration": record["configuration"],
        "kind": kind,
        "binary_sha256": record["binary_sha256"],
        "oracle_manifest_sha256": sha(oracle / "manifest.json"),
        "oracle": str(oracle),
        "cases": results,
        "complete_node_arrays_compared": sum(c["nodes_compared"] for c in results),
    }
    (directory / kind / "differential.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    return report


def spike(directory):
    record = verify_build(directory, "rv64")
    simulator = ROOT / ".deps/spike/bin/spike"
    text = run(
        [simulator, "--isa=rv64imc", ROOT / record["binary"]], timeout=300
    ).replace("\r", "")
    (directory / "rv64/spike-output.txt").write_text(text)
    match = re.search(r"^output_hex=([0-9a-f]{2000})$", text, re.MULTILINE)
    if (
        not match
        or bytes.fromhex(match.group(1))
        != (ROOT / "tests/compiler/fixtures/baseline-output.bin").read_bytes()
    ):
        raise ModelError("RV64 A0 full public output differs from B0")
    watermark = int(re.search(r"stack_watermark_bytes=(\d+)", text).group(1))
    if watermark >= 1024 * 1024:
        raise ModelError("A0 exceeded the reserved stack")
    report = {
        "status": "PASS",
        "configuration": record["configuration"],
        "binary_sha256": record["binary_sha256"],
        "simulator_sha256": sha(simulator),
        "command": [str(simulator), "--isa=rv64imc", record["binary"]],
        "full_output_bytes_compared": 1000,
        "stack_watermark_bytes": watermark,
        "stack_scope": "observed baseline paint watermark, includes unpainted safety gap; not a proof of minimum SP or a universal stack bound",
        "stdout_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    (directory / "rv64/spike-verification.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    print(text[: text.index("output_hex=")], end="")
    print(f"RV64 {record['configuration']} all 1000 output bytes match B0: PASS")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "compare", "spike"))
    parser.add_argument(
        "--kind", choices=("native", "capture", "sanitized", "rv64"), default="capture"
    )
    parser.add_argument("--generated-dir", type=Path, default=GENERATED)
    args = parser.parse_args()
    args.generated_dir = args.generated_dir.resolve()
    try:
        if args.command == "build":
            build(args.generated_dir, args.kind)
        elif args.command == "compare":
            differential(args.generated_dir, args.kind)
        else:
            spike(args.generated_dir)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stdout, error.stderr, file=sys.stderr)
        parser.exit(1, f"A0 {args.command} failed: {error}\n")


if __name__ == "__main__":
    main()
