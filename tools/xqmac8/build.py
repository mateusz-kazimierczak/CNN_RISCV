#!/usr/bin/env python3
"""Build ABI-specific Xqmac8 libraries without changing pinned Spike trees."""

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.xqmac8.runtime import digest

REVISION = "19609434bb3d83448eec8796e8f0367c868efbda"


def build(variant):
    suffix = "" if variant == "ordinary" else "-profile"
    source = ROOT / (".deps/riscv-isa-sim" + suffix)
    configured = ROOT / (".deps/spike" + suffix + "-build")
    simulator = ROOT / (".deps/spike" + suffix + "/bin/spike")
    if (
        subprocess.check_output(
            ["git", "-C", source, "rev-parse", "HEAD"], text=True
        ).strip()
        != REVISION
    ):
        raise ValueError("unexpected Spike revision")
    expected_patch = ROOT / "tools/spike_profile/spike.patch"
    expected_diff = expected_patch.read_text().rstrip() if variant == "profile" else ""
    actual_diff = subprocess.check_output(
        ["git", "-C", source, "diff", "HEAD", "--"], text=True
    ).rstrip()
    if actual_diff != expected_diff:
        raise ValueError("unexpected changes in Spike sources; preserve them before rebuilding")
    default_cxx = (
        "/Library/Developer/CommandLineTools/usr/bin/clang++"
        if sys.platform == "darwin"
        else "c++"
    )
    compiler = shutil.which(os.environ.get("CXX", default_cxx))
    output = ROOT / "build/xqmac8" / variant
    output.mkdir(parents=True, exist_ok=True)
    library = output / (
        "libxqmac8.dylib" if sys.platform == "darwin" else "libxqmac8.so"
    )
    command = [compiler, "-std=c++20", "-O2", "-fPIC"]
    link_flags = ["-shared"]
    if sys.platform == "darwin":
        command += [
            "-isysroot",
            "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk",
        ]
        link_flags += ["-undefined", "dynamic_lookup"]
    for include in (
        configured,
        source,
        source / "riscv",
        source / "disasm",
        source / "fesvr",
        source / "softfloat",
    ):
        command += ["-I", str(include)]
    extension = ROOT / "tools/xqmac8/extension.cc"
    # Freeze compiler-discovered transitive headers, including generated config.h.
    dependency_text = subprocess.check_output(
        [*command, "-M", "-MT", "extension", extension], text=True
    )
    deps = shlex.split(dependency_text.replace("\\\n", "").split(":", 1)[1])
    inputs = [Path(p).resolve() for p in deps] + [
        simulator,
        Path(__file__),
        ROOT / "tools/xqmac8/runtime.py",
        Path(compiler),
    ]
    if variant == "profile":
        inputs.append(expected_patch)
    key = lambda p: str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
    hashes = {key(p): digest(p) for p in inputs}
    record_path = output / "build.json"
    if record_path.exists() and library.exists():
        old = json.loads(record_path.read_text())
        if (
            old["inputs_sha256"] == hashes
            and old["library_sha256"] == digest(library)
            and old["command"] == [*command, *link_flags, str(extension), "-o", str(library)]
        ):
            print(f"Xqmac8 {variant}: verified existing build")
            return old
    command += [*link_flags, str(extension), "-o", str(library)]
    subprocess.run(command, check=True)
    if any(digest(ROOT / p) != h for p, h in hashes.items()):
        raise ValueError("extension inputs changed during build")
    record = {
        "schema_version": 1,
        "variant": variant,
        "spike_revision": REVISION,
        "library": str(library.relative_to(ROOT)),
        "library_sha256": digest(library),
        "inputs_sha256": hashes,
        "command": command,
    }
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"Xqmac8 {variant}: built {library}")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant", choices=("ordinary", "profile", "all"), default="all"
    )
    args = parser.parse_args()
    for variant in (
        ("ordinary", "profile") if args.variant == "all" else (args.variant,)
    ):
        build(variant)
