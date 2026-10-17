#!/usr/bin/env python3
"""Build a separate machine-controlled Spike; never modify baseline/profiler trees."""

from pathlib import Path
import argparse, hashlib, os, shutil, subprocess

ROOT = Path(__file__).resolve().parents[2]
REVISION = "19609434bb3d83448eec8796e8f0367c868efbda"


def run(*args, cwd=ROOT, **kw):
    return subprocess.run(args, cwd=cwd, check=True, **kw)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jobs", type=int, default=8)
    a = p.parse_args()
    source = ROOT / ".deps/riscv-isa-sim-debug"
    build = ROOT / ".deps/spike-debug-build"
    prefix = ROOT / ".deps/spike-debug"
    assets = ROOT / "tools/spike_debug"
    if not source.exists():
        run("git", "clone", "--shared", str(ROOT / ".deps/riscv-isa-sim"), str(source))
        run("git", "checkout", "--detach", REVISION, cwd=source)
    if (
        run(
            "git", "rev-parse", "HEAD", cwd=source, capture_output=True, text=True
        ).stdout.strip()
        != REVISION
    ):
        raise SystemExit("debug Spike revision mismatch")
    patch = (assets / "spike.patch").read_text()
    diff = run("git", "diff", cwd=source, capture_output=True, text=True).stdout
    if not diff:
        run("git", "apply", "--check", str(assets / "spike.patch"), cwd=source)
        run("git", "apply", str(assets / "spike.patch"), cwd=source)
    elif diff.rstrip() != patch.rstrip():
        raise SystemExit(
            "Unexpected debug dependency changes; preserve and move the tree aside."
        )
    headers = [assets / "host_debug_hooks.h", assets / "host_debugger.h"]
    key = hashlib.sha256(
        REVISION.encode() + patch.encode() + b"".join(f.read_bytes() for f in headers)
    ).hexdigest()
    stamp = build / "debug-build.sha256"
    if (
        stamp.exists()
        and stamp.read_text().strip() == key
        and (prefix / "bin/spike").exists()
    ):
        return
    for f in headers:
        destination = source / "riscv" / f.name
        if not destination.exists() or destination.read_bytes() != f.read_bytes():
            shutil.copyfile(f, destination)
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
    run("gmake", "-s", f"-j{a.jobs}", cwd=build, env=env)
    run("gmake", "-s", "install", cwd=build, env=env)
    stamp.write_text(key + "\n")


if __name__ == "__main__":
    main()
