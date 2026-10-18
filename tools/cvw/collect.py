#!/usr/bin/env python3
"""Collect a small, explicit progress/result snapshot from the Windows WSL host."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--run-label", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results/cvw/baseline")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.run_label):
        parser.error("run label must be a plain identifier")
    script = "set -eu\ncd ~/code/arch_project\npython3 - <<'CVW_SNAPSHOT'\n"
    script += "import hashlib,json\nfrom pathlib import Path\n"
    script += f"label={args.run_label!r}\n"
    script += """result = {'runs': {}}
for name in ('B0', 'B1'):
    directory = Path('build/cvw/runs') / (name + '-' + label)
    record = json.loads((directory / 'run.json').read_text())
    if record['status'] == 'RUNNING':
        process = Path('/proc') / str(record.get('runner_pid', 0)) / 'cmdline'
        command = process.read_bytes() if process.exists() else b''
        if b'tools/cvw/run.py' not in command or (name + '-' + label).encode() not in command:
            record = json.loads((directory / 'run.json').read_text())
            if record['status'] == 'RUNNING':
                record = dict(record, status='INTERRUPTED', error='No live runner for this run directory')
    log = (directory / 'simulation.log').read_text(errors='replace')
    result['runs'][name] = {'record': record, 'progress_lines': [line for line in log.splitlines() if line.startswith('PROJECT ')]}
smoke = Path('build/cvw/smoke/verification.json')
result['smoke'] = json.loads(smoke.read_text()) if smoke.exists() else None
binary = Path('build/cvw/wally/sim/verilator/wkdir/arch_project_rv64imc_testbench/Vtestbench')
result['simulator_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
print(json.dumps(result))
CVW_SNAPSHOT
"""
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/cvw_remote.py"), "--host", args.host],
        input=script,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    snapshot = json.loads(result.stdout)
    contract = json.loads(Path(__file__).with_name("workloads.json").read_text())
    summary = {
        "schema_version": 1,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_label": args.run_label,
        "simulator_sha256": snapshot["simulator_sha256"],
        "smoke": snapshot["smoke"],
        "runs": {},
        "physical_clock_frequency": {"evidence": "unavailable", "value": None},
        "area": {"evidence": "unavailable", "value": None},
    }
    for name, value in snapshot["runs"].items():
        record = value["record"]
        if record["elf_sha256"] != contract[name]["elf_sha256"]:
            raise ValueError(f"unexpected {name} ELF")
        data = {
            "status": record["status"],
            "elf_sha256": record["elf_sha256"],
            "expected_instructions": contract[name]["expected_instructions"],
            "integration": record["integration"],
            "progress_lines": value["progress_lines"],
            "cycles": None,
            "instructions": None,
            "evidence": "unavailable until complete verified inference",
        }
        if record["status"] == "PASS":
            if (
                record["output_bytes_compared"] != 1000
                or record["output_sha256"] != contract["expected_output_sha256"]
            ):
                raise ValueError(f"incomplete {name} output validation")
            if (
                record["metrics"]["instructions"]
                != contract[name]["expected_instructions"]
            ):
                raise ValueError(f"unexpected {name} retirements")
            data.update(
                record["metrics"],
                evidence="measured",
                output_bytes_compared=1000,
                output_sha256=record["output_sha256"],
            )
        summary["runs"][name] = data
    if summary["runs"]["B0"]["integration"] != summary["runs"]["B1"]["integration"]:
        raise ValueError("B0/B1 core or monitor configurations differ")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    lines = [
        "# CV-Wally baseline bring-up",
        "",
        "Preserved B0 and accepted software B1 run on the same pinned RV64IMC core.",
        "Full-model metrics require clean exit, exact retirement agreement and",
        "complete 1,000-byte reference-output comparison.",
        "",
        "| Configuration | State | Invocation retirements | Invocation cycles |",
        "|---|---|---:|---:|",
    ]
    for name, data in summary["runs"].items():
        count = (
            f"{int(data['instructions']):,}"
            if data["instructions"] is not None
            else "pending"
        )
        cycles = f"{int(data['cycles']):,}" if data["cycles"] is not None else "pending"
        lines.append(f"| {name} | {data['status']} | {count} | {cycles} |")
    lines += [
        "",
        "The directed fixture passes 19 retirements, complete unaligned output",
        "comparison, repeated HTIF acknowledgement, wrong-count rejection and",
        "incomplete-run rejection. Details and partial progress are in [summary.json](summary.json).",
        "",
        "A partial progress count is not a completed inference metric. Physical",
        "clock frequency and area remain unmeasured in this simulation checkpoint.",
        "",
        "[Configuration, scope and reproduction](../../../docs/cvw-verilator.md).",
        "",
    ]
    (args.output / "README.md").write_text("\n".join(lines))
    raw = ROOT / "build/cvw/remote" / args.run_label
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({name: data["status"] for name, data in summary["runs"].items()}))


if __name__ == "__main__":
    main()
