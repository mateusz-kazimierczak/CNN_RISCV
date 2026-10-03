#!/usr/bin/env python3
"""Build an isolated, pinned Spike with the tracked retirement profiler."""

from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = "19609434bb3d83448eec8796e8f0367c868efbda"


def run(*args: str, cwd: Path = ROOT, **kwargs):
    return subprocess.run(args, cwd=cwd, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    source = ROOT / ".deps/riscv-isa-sim-profile"
    build = ROOT / ".deps/spike-profile-build"
    prefix = ROOT / ".deps/spike-profile"
    patch = ROOT / "tools/spike_profile/spike.patch"
    header = ROOT / "tools/spike_profile/roi_profiler.h"
    if not source.exists():
        run("git", "clone", "--shared", str(ROOT / ".deps/riscv-isa-sim"), str(source))
    revision = run(
        "git", "rev-parse", "HEAD", cwd=source, capture_output=True, text=True
    ).stdout.strip()
    if revision != REVISION:
        raise SystemExit(f"profiling Spike revision mismatch: {revision}")
    diff = run("git", "diff", cwd=source, capture_output=True, text=True).stdout
    if not diff:
        run("git", "apply", "--check", str(patch), cwd=source)
        run("git", "apply", str(patch), cwd=source)
    elif diff.rstrip() != patch.read_text().rstrip():
        raise SystemExit(
            "profiling dependency has unexpected changes; preserve it and move it aside"
        )
    key = hashlib.sha256(
        REVISION.encode() + patch.read_bytes() + header.read_bytes()
    ).hexdigest()
    stamp = build / "profile-build.sha256"
    if (
        stamp.exists()
        and stamp.read_text().strip() == key
        and (prefix / "bin/spike").exists()
    ):
        return
    shutil.copyfile(header, source / "riscv/roi_profiler.h")
    build.mkdir(parents=True, exist_ok=True)
    prefix.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if shutil.which("xcrun"):
        env["SDKROOT"] = run(
            "xcrun",
            "--sdk",
            "macosx",
            "--show-sdk-path",
            capture_output=True,
            text=True,
        ).stdout.strip()
    if not (build / "Makefile").exists():
        run(str(source / "configure"), f"--prefix={prefix}", cwd=build, env=env)
    run("gmake", "-s", f"-j{args.jobs}", cwd=build, env=env)
    run("gmake", "-s", "install", cwd=build, env=env)
    stamp.write_text(key + "\n")


if __name__ == "__main__":
    main()
