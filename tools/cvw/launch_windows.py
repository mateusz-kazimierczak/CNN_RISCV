#!/usr/bin/env python3
"""Start a Windows-owned WSL simulation suite that survives SSH disconnection.

Win32_Process.Create starts wsl.exe through Windows' local process service, so
it does not inherit the SSH session's job lifetime. No service, scheduled task,
registry change or administrator installation is created.
"""

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--distribution", default="Ubuntu-22.04")
    parser.add_argument("--project", default="/home/mat/code/arch_project")
    parser.add_argument("--suite", choices=("baseline", "custom", "postinc", "dwmac", "x5"), default="baseline")
    parser.add_argument(
        "--run-label", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    args = parser.parse_args()
    for value in (args.distribution, args.run_label):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            parser.error("distribution and run label must be plain identifiers")
    if (
        not re.fullmatch(r"/[A-Za-z0-9_./-]+", args.project)
        or ".." in Path(args.project).parts
    ):
        parser.error(
            "project must be an absolute Linux path without shell metacharacters"
        )
    if args.host.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_.@:-]+", args.host):
        parser.error("invalid host")
    arguments = f" -d {args.distribution} --exec bash {args.project}/tools/cvw/windows_suite.sh {args.run_label} {args.suite}"
    powershell = (
        "$ProgressPreference = 'SilentlyContinue'; $ErrorActionPreference = 'Stop'; "
        "$command = [IO.Path]::Combine([Environment]::SystemDirectory, 'wsl.exe') + "
        + repr(arguments)
        + "; "
        "$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=$command}; "
        "$result | Select-Object ReturnValue,ProcessId | ConvertTo-Json -Compress"
    )
    encoded = base64.b64encode(powershell.encode("utf-16le")).decode()
    result = subprocess.run(
        [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            args.host,
            "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded,
        ],
        text=True,
        stdout=subprocess.PIPE,
        check=True,
        timeout=60,
    )
    record = json.loads(result.stdout)
    if record["ReturnValue"] != 0:
        raise RuntimeError(f"Windows process creation failed: {record}")
    record.update(
        run_label=args.run_label,
        project=args.project,
        distribution=args.distribution,
        suite=args.suite,
        state="LAUNCHED; verify Linux runner records before accepting results",
    )
    output = Path(__file__).resolve().parents[2] / "build/cvw"
    output.mkdir(parents=True, exist_ok=True)
    (output / ("windows-launch-" + args.run_label + ".json")).write_text(
        json.dumps(record, indent=2) + "\n"
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
