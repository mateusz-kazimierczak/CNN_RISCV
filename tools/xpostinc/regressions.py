#!/usr/bin/env python3
"""Run the complete compiler suite in independent processes and bind its evidence."""

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.xqmac8.runtime import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=4, choices=range(1, 5))
    args = parser.parse_args()
    output = ROOT / "build/xpostinc"
    output.mkdir(parents=True, exist_ok=True)
    modules = sorted(p.stem for p in (ROOT / "tests/compiler").glob("test_*.py"))
    sources = [
        p
        for folder in ("compiler", "kernels", "tests/compiler")
        for p in (ROOT / folder).rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix in (".py", ".cc", ".h", ".json", ".bin")
    ]
    sources.append(Path(__file__))
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}

    def group(index):
        selected = modules[index :: args.jobs]
        path = output / f"compiler-group-{index + 1}.log"
        command = [sys.executable, "-m", "unittest", *selected, "-v"]
        env = dict(os.environ, PYTHONPATH=str(ROOT / "tests/compiler"))
        with path.open("w") as log:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=1200,
            )
        text = path.read_text()
        match = re.search(r"Ran (\d+) tests? in", text)
        if result.returncode or not match or not re.search(r"^OK$", text, re.MULTILINE):
            raise RuntimeError(
                f"Compiler regression group {index + 1} failed: {path}\n{text[-6000:]}"
            )
        print(f"Compiler group {index + 1}: PASS ({match[1]} tests)", flush=True)
        return {
            "modules": selected,
            "count": int(match[1]),
            "log": str(path.relative_to(ROOT)),
            "log_sha256": digest(path),
            "command": command,
        }

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        groups = list(pool.map(group, range(args.jobs)))
    if any(digest(ROOT / name) != sha for name, sha in hashes.items()):
        raise ValueError("Regression sources changed while tests ran")
    report = {
        "status": "PASS",
        "modules": modules,
        "groups": groups,
        "count": sum(g["count"] for g in groups),
        "source_sha256": hashes,
    }
    (output / "compiler-regressions.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"Compiler regressions: PASS ({report['count']} tests, all {len(modules)} modules)"
    )


if __name__ == "__main__":
    main()
