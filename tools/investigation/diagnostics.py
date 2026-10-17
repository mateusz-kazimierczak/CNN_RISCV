"""GCC analysis of frozen generated code; attach only after loaded-byte equality."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from explorer.compiler import extract_functions
from profile_spike import Elf

from compiler.build_evidence import canonical, digest, local_file, open_build

from .build import compile_checked
from .common import (
    ROOT,
    materialize,
    original_root,
    rewrite_command,
    run,
    seal,
    verify_archive,
    verify_toolchain,
)

FORMAT = "compiler-gcc-analysis"
STAGES = {
    "original": "Original tree",
    "gimple": "Initial GIMPLE",
    "optimized": "Optimized GIMPLE",
    "expand": "RTL expansion",
    "final": "Final RTL",
    "inline": "Inlining analysis",
}
REQUIRED = {
    "Original tree",
    "Initial GIMPLE",
    "Optimized GIMPLE",
    "RTL expansion",
    "Final RTL",
    "Inlining analysis",
    "Emitted assembly",
    "Optimization remarks",
    "Pass discovery",
}


def remove_outputs(command):
    result = []
    skip = False
    for arg in command:
        if skip:
            skip = False
        elif arg in ("-o", "-MF", "-MT", "-MQ"):
            skip = True
        elif arg not in ("-c", "-MD", "-MMD", "-MP"):
            result.append(arg)
    return result


def same_loaded_image(measured, analysis):
    a, b = Elf(measured), Elf(analysis)
    if a.allocated() != b.allocated() or a.loads != b.loads:
        raise ValueError(
            "GCC analysis changes loaded bytes/layout; cannot attach to measured ELF"
        )


def verify_analysis(path):
    path, manifest = verify_archive(path, FORMAT)
    data = json.loads((path / "compiler_analysis.json").read_text())
    if data["schema_version"] != 2 or not data["loadable_identical"]:
        raise ValueError("unverified GCC analysis")
    measured = local_file(path, data["measured_elf"])
    analysis = local_file(path, data["analysis_elf"])
    if (
        digest(measured) != data["measured_elf_sha256"]
        or digest(analysis) != data["analysis_elf_sha256"]
    ):
        raise ValueError("GCC analysis ELF identity mismatch")
    same_loaded_image(measured, analysis)
    if manifest["build_evidence_sha256"] != data["build_evidence_sha256"]:
        raise ValueError("GCC analysis build linkage mismatch")
    for unit in data["units"]:
        if not REQUIRED <= {a["stage"] for a in unit["artifacts"]}:
            raise ValueError("incomplete compiler diagnostics")
        for artifact in unit["artifacts"]:
            if digest(local_file(path, artifact["path"])) != artifact["sha256"]:
                raise ValueError("GCC artifact hash mismatch")
    return path, data


def analyze(args):
    args.output_root = args.output_root.resolve()
    snapshot, evidence = open_build(args.build_manifest.resolve())
    if (
        evidence["build"]["kind"] != "rv64"
        or evidence["build"]["configuration"] != "A0"
    ):
        raise ValueError("GCC investigation requires a measured RV64 A0 build")
    compiler = verify_toolchain(evidence)
    original = original_root(evidence)
    args.output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".analysis-", dir=args.output_root
    ) as temporary:
        work = Path(temporary) / "artifact"
        work.mkdir()
        shutil.copytree(snapshot.parent, work / "build_evidence")
        workspace = work / "workspace"
        materialize(snapshot, evidence, workspace)
        source_root = work / "investigation_sources"
        source_root.mkdir()
        for source in sorted((ROOT / "tools/investigation").glob("*.py")):
            shutil.copyfile(source, source_root / source.name)
        env = dict(os.environ)
        units, inventory = [], []
        for index, recorded in enumerate(evidence["build"]["commands"]):
            command = rewrite_command(recorded, original, workspace)
            if "-c" not in command:
                run(command, env=env)
                inventory.append(command)
                continue
            source = Path(command[command.index("-c") + 1])
            output = Path(command[command.index("-o") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            selected = (
                source.suffix in (".cc", ".cpp", ".c") and source.name != "constants.cc"
            )
            if source.suffix == ".S":
                run(command, env=env)
                inventory.append(command)
                continue
            # Drop only dependency-output switches; optimization/ABI flags stay.
            base, skip = [], False
            for arg in command:
                if skip:
                    skip = False
                elif arg == "-MF":
                    skip = True
                elif arg != "-MD":
                    base.append(arg)
            position = base.index("-c")
            flags = [f"-ffile-prefix-map={workspace}={original}"]
            if selected:
                directory = work / "gcc" / f"unit-{index}"
                directory.mkdir(parents=True)
                flags += [
                    "-save-temps=obj",
                    "-dumpdir",
                    str(directory) + "/",
                    "-dumpbase",
                    source.name,
                    "-fdump-tree-original-lineno",
                    "-fdump-tree-gimple-lineno",
                    "-fdump-tree-optimized-lineno",
                    "-fdump-rtl-expand",
                    "-fdump-rtl-final",
                    "-fdump-ipa-inline",
                    f"-fopt-info-all={directory / 'remarks.txt'}",
                ]
            actual, dependencies = compile_checked(
                [*base[:position], *flags, *base[position:]], source, output, env
            )
            for name, sha in dependencies.items():
                unmap = name.replace(str(workspace) + "/", original + "/")
                key = unmap.removeprefix(original + "/")
                if evidence["files"].get(key, {}).get("sha256") != sha:
                    raise ValueError(
                        f"GCC analysis dependency differs from frozen build: {key}"
                    )
            inventory.append(actual)
            if not selected:
                continue
            discovery = run(
                [*remove_outputs(base), "-fsyntax-only", "-fdump-passes"], env=env
            )
            (directory / "passes.txt").write_text(discovery.stderr)
            artifacts = []
            for path in sorted(directory.iterdir()):
                stage = STAGES.get(path.suffix.removeprefix("."))
                stage = {".s": "Emitted assembly"}.get(path.suffix, stage)
                stage = {
                    "remarks.txt": "Optimization remarks",
                    "passes.txt": "Pass discovery",
                }.get(path.name, stage)
                if stage:
                    artifacts.append(
                        {
                            "stage": stage,
                            "path": str(path.relative_to(work)),
                            "sha256": digest(path),
                            "functions": extract_functions(
                                path.read_text(errors="replace"), path.suffix == ".s"
                            ),
                        }
                    )
            if not REQUIRED <= {a["stage"] for a in artifacts}:
                raise ValueError(f"missing diagnostics for {source.name}")
            # Preprocessed headers are not a useful viewer artifact; sources are
            # already frozen. Keep the indexed diagnostics and object reports.
            for path in directory.glob("*.ii"):
                path.unlink()
            units.append(
                {
                    "id": f"unit-{index}",
                    "source": str(source.relative_to(workspace)),
                    "arguments": actual,
                    "base_arguments": recorded,
                    "dependency_sha256": dependencies,
                    "artifacts": artifacts,
                }
            )
            print(f"GCC evidence: {source.name}", flush=True)
        measured_key = evidence["files"][evidence["build"]["binary"]]["blob"]
        measured = work / "build_evidence" / measured_key
        binary = workspace / evidence["build"]["binary"]
        same_loaded_image(measured, binary)
        data = {
            "schema_version": 2,
            "configuration": "A0",
            "build_evidence_sha256": digest(snapshot),
            "measured_elf": str(measured.relative_to(work)),
            "measured_elf_sha256": digest(measured),
            "analysis_elf": str(binary.relative_to(work)),
            "analysis_elf_sha256": digest(binary),
            "loadable_identical": True,
            "compiler_binary_sha256": digest(compiler),
            "build_root": str(work),
            "units": units,
            "commands": inventory,
            "source_prefix_map": {str(workspace): original},
        }
        (work / "compiler_analysis.json").write_text(canonical(data))
        destination = seal(
            work, args.output_root, FORMAT, {"build_evidence_sha256": digest(snapshot)}
        )
    report(destination, args.results_dir)
    print(
        f"Verified GCC analysis: {len(units)} executable translation units; all loaded bytes identical\n{destination}",
        flush=True,
    )


def report(path, output):
    path, data = verify_analysis(path)
    output = Path(output).resolve()
    if output.is_relative_to(path):
        raise ValueError("report cannot modify sealed GCC evidence")
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        canonical(
            {
                "artifact_id": path.name,
                "measured_elf_sha256": data["measured_elf_sha256"],
                "analysis_elf_sha256": data["analysis_elf_sha256"],
                "loadable_identical": True,
                "units": [
                    {
                        "source": u["source"],
                        "stages": [a["stage"] for a in u["artifacts"]],
                    }
                    for u in data["units"]
                ],
            }
        )
    )
    lines = [
        "# A0 GCC investigation",
        "",
        f"Artifact: `{path.name}`.",
        "",
        f"Measured ELF: `{data['measured_elf_sha256']}`.",
        f"Analysis ELF: `{data['analysis_elf_sha256']}`.",
        "",
        "All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.",
        "",
        "| Executable translation unit | Diagnostic stages |",
        "|---|---:|",
    ]
    lines += [f"| {u['source']} | {len(u['artifacts'])} |" for u in data["units"]]
    lines += [
        "",
        "GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.",
        "",
    ]
    (output / "README.md").write_text("\n".join(lines))
    return data
