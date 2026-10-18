#!/usr/bin/env python3
"""Run a bash script in Windows WSL through the Windows OpenSSH server.

Pass the script on stdin or with --script. This keeps bash quoting inside bash;
PowerShell/cmd never interprets the script body. No SSH server inside WSL is
needed. Use --user root only for explicitly requested dependency installation.
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--distribution", default="Ubuntu-22.04")
    parser.add_argument("--user")
    parser.add_argument("--script", type=Path)
    parser.add_argument(
        "--upload",
        type=Path,
        action="append",
        default=[],
        help="Copy a project-relative file to the WSL project before running the script",
    )
    parser.add_argument(
        "--project",
        default="code/arch_project",
        help="Project directory relative to the WSL user's home",
    )
    args = parser.parse_args()
    for value in (args.distribution, args.user):
        if value and not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            parser.error("distribution and user must be plain identifiers")
    if args.host.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_.@:-]+", args.host):
        parser.error("invalid SSH host")
    command = f"wsl.exe -d {args.distribution}"
    if args.user:
        command += f" -u {args.user}"
    command += " --exec bash -s"
    script = args.script.read_bytes() if args.script else sys.stdin.buffer.read()
    if args.upload:
        project = Path(args.project)
        if project.is_absolute() or ".." in project.parts:
            parser.error("project must stay inside the WSL user's home")
        preamble = (
            "set -eu\npython3 - <<'CVW_COPY'\nimport base64\nfrom pathlib import Path\n"
        )
        preamble += f"root = Path.home() / {args.project!r}\n"
        for path in args.upload:
            if path.is_absolute() or ".." in path.parts or not path.is_file():
                parser.error(f"upload must name a project-relative file: {path}")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            preamble += f"p = root / {path.as_posix()!r}\np.parent.mkdir(parents=True, exist_ok=True)\n"
            preamble += f"p.write_bytes(base64.b64decode({encoded!r}))\n"
        script = (preamble + "CVW_COPY\n").encode() + script
    result = subprocess.run(
        [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            args.host,
            command,
        ],
        input=script,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
