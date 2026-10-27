"""Compile replay harnesses against a materialized, verified production build."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

from compiler.build_evidence import canonical, digest
from compiler.replay import emit_adapter, emit_fixture_header

from .common import ROOT, TOOLCHAIN, materialize, original_root, run, verify_toolchain


def depnames(text):
    return shlex.split(text.replace("\\\n", "").split(":", 1)[1])


def compile_checked(command, source, output, env):
    flags = command[1 : command.index("-c")]
    pre = run([command[0], *flags, "-M", "-MT", "unit", source], env=env).stdout
    before = {str(Path(p).resolve()): digest(p) for p in depnames(pre)}
    depfile = output.with_suffix(".d")
    actual = [*command, "-MD", "-MF", str(depfile)]
    run(actual, env=env)
    after = {str(Path(p).resolve()): digest(p) for p in depnames(depfile.read_text())}
    if before != after:
        raise ValueError("investigation dependencies changed during compilation")
    return actual, after


def prepare_sources(work, snapshot, evidence, workload, pack):
    shutil.copytree(snapshot.parent, work / "build_evidence")
    workspace = work / "workspace"
    materialize(snapshot, evidence, workspace)
    original = original_root(evidence)
    generated = Path(evidence["artifacts"]["model.cc"]).parent
    source = workspace / "replay"
    source.mkdir()
    (source / "fixtures.bin").write_bytes(pack)
    (source / "fixtures.json").write_text(canonical(workload))
    (source / "replay_fixtures.h").write_text(emit_fixture_header(workload))
    (source / "model_adapter.cc").write_text(
        emit_adapter(workspace / generated / "model.cc", evidence)
    )
    shutil.copyfile(ROOT / "tools/compiler/replay_driver.cc", source / "driver.cc")
    (source / "fixtures.S").write_text(
        """#ifdef __APPLE__
.section __TEXT,__const
.globl _replay_fixture_begin
.balign 16
_replay_fixture_begin:
#else
.section .rodata.replay,"a",@progbits
.globl replay_fixture_begin
.balign 16
replay_fixture_begin:
#endif
"""
        + f'.incbin "{source / "fixtures.bin"}"\n'
    )
    (work / "workload.json").write_text(canonical(workload))
    return workspace, source, generated, original


def build_replay(work, evidence, kind):
    compiler = (
        verify_toolchain(evidence)
        if kind == "rv64"
        else (
            os.environ.get(
                "COMPILER_SANITIZER_CXX",
                "/Library/Developer/CommandLineTools/usr/bin/clang++"
                if sys.platform == "darwin"
                else "g++",
            )
            if kind == "sanitized"
            else "g++"
        )
    )
    workspace, source = work / "workspace", work / "workspace/replay"
    generated = Path(evidence["artifacts"]["model.cc"]).parent
    original = original_root(evidence)
    command = evidence["build"]["commands"][0]
    flags = [
        arg.replace(original + "/", str(workspace) + "/")
        for arg in command[1 : command.index("-MD")]
    ]
    if kind != "rv64":
        flags = [
            arg
            for arg in flags
            if not arg.startswith(("-march=", "-mabi=", "-mcmodel="))
        ]
    flags += [
        "-I",
        str(source),
        f"-DREPLAY_NATIVE={int(kind != 'rv64')}",
        f"-ffile-prefix-map={workspace}={original}",
    ]
    if evidence["build"]["configuration"] in ("X1", "X2", "X3", "X4", "X5"):
        flags.append("-DXQMAC8_REPLAY=1")
    if kind == "sanitized":
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    env = dict(os.environ)
    if sys.platform == "darwin":
        env["SDKROOT"] = run(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"]
        ).stdout.strip()
    upstream = workspace / ".deps/tflite-micro"
    sources = [
        workspace / generated / "constants.cc",
        source / "model_adapter.cc",
        workspace / "kernels/reference/numerics.cc",
        upstream / "tensorflow/lite/kernels/internal/common.cc",
        source / "driver.cc",
        source / "fixtures.S",
    ]
    if evidence["generation"].get("runtime", "reference") != "reference":
        sources = [workspace / generated / "constants.cc", source / "model_adapter.cc"]
        for cmd in evidence["build"]["commands"]:
            if "-c" not in cmd:
                continue
            original_source = cmd[cmd.index("-c") + 1]
            if "/kernels/" in original_source and original_source.endswith(".cc"):
                sources.append(
                    Path(original_source.replace(original + "/", str(workspace) + "/"))
                )
        if evidence["generation"].get("runtime") == "standalone":
            sources.append(workspace / "kernels/project/replay.cc")
        sources += [source / "driver.cc", source / "fixtures.S"]
    if kind == "rv64":
        sources += [
            workspace / "tflm/platform/rv64imc/syscalls.cc",
            workspace / "tflm/platform/rv64imc/crt0.S",
        ]
    out = work / kind
    out.mkdir()
    commands, deps, objects = [], {}, []
    for index, src in enumerate(sources):
        obj = out / f"{index}_{src.stem}.o"
        if src.suffix == ".S":
            asmflags = [f"-DREPLAY_NATIVE={int(kind != 'rv64')}", "-g"]
            if kind == "rv64":
                asmflags += ["-march=rv64imc", "-mabi=lp64", "-mcmodel=medany"]
            actual = [compiler, *asmflags, "-c", str(src), "-o", str(obj)]
            run(actual, env=env)
            dependencies = {
                str(src): digest(src),
                str(source / "fixtures.bin"): digest(source / "fixtures.bin"),
            }
        else:
            actual, dependencies = compile_checked(
                [compiler, *flags, "-c", str(src), "-o", str(obj)], src, obj, env
            )
        for name, sha in dependencies.items():
            if name in deps and deps[name] != sha:
                raise ValueError("dependency changed between compilation units")
        deps.update(dependencies)
        commands.append(actual)
        objects.append(obj)
    binary = out / ("replay.elf" if kind == "rv64" else "replay")
    linkflags = (
        [
            "-nostartfiles",
            "-static",
            "-Wl,--gc-sections",
            f"-Wl,-T,{workspace / 'tflm/platform/rv64imc/link.ld'}",
            f"-Wl,-Map,{out / 'replay.map'}",
        ]
        if kind == "rv64"
        else (
            ["-Wl,-dead_strip"] if sys.platform == "darwin" else ["-Wl,--gc-sections"]
        )
    )
    actual = [compiler, *flags, *map(str, objects), *linkflags, "-o", str(binary)]
    run(actual, env=env)
    commands.append(actual)
    if kind == "rv64":
        audit = run(
            [
                sys.executable,
                ROOT / "tools/audit_isa_elf.py",
                "--configuration",
                evidence["build"]["configuration"],
                "--readelf",
                str(TOOLCHAIN) + "readelf",
                "--objdump",
                str(TOOLCHAIN) + "objdump",
                binary,
            ]
        ).stdout
        (out / "isa-audit.txt").write_text(audit)
        names = run([str(TOOLCHAIN) + "nm", "-C", binary]).stdout
        if any(
            token in names
            for token in (
                " malloc",
                " calloc",
                " realloc",
                " _sbrk",
                "operator new",
                "MicroInterpreter",
                "MicroAllocator",
            )
        ):
            raise ValueError("RV64 replay linked heap/interpreter code")
        (out / "symbols.txt").write_text(names)
    # Paths are retained as argv values with an explicit artifact-root mapping.
    record = {
        "schema_version": 2,
        "kind": kind,
        "binary": str(binary.relative_to(work)),
        "binary_sha256": digest(binary),
        "compiler": run([compiler, "--version"]).stdout.splitlines()[0],
        "compiler_binary_sha256": digest(shutil.which(compiler)),
        "commands": commands,
        "build_root": str(work),
        "environment": {"SDKROOT": env.get("SDKROOT")},
        "dependency_sha256": deps,
    }
    frozen = out / "dependencies"
    frozen.mkdir()
    record["dependency_files"] = {}
    for name, sha in deps.items():
        if digest(name) != sha:
            raise ValueError("dependency changed before freezing replay build")
        target = frozen / sha
        if not target.exists():
            shutil.copyfile(name, target)
        record["dependency_files"][name] = str(target.relative_to(work))
    (out / "build.json").write_text(canonical(record))
    print(f"Replay {kind} built: {len(sources)} translation units", flush=True)
    return binary
