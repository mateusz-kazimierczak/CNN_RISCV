#!/usr/bin/env python3
"""Collect selected custom inference evidence without accepting partial results."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def validate_pass(record, workload, expected_hash, output):
    if record["elf_sha256"] != workload["elf_sha256"] or record["workload"] != workload:
        raise ValueError("wrong checkpoint executable or workload")
    metrics = record["metrics"]
    if metrics["instructions"] != workload["expected_instructions"] or metrics["custom_instructions"] != workload["custom_instructions"]:
        raise ValueError("RTL retirements disagree with saved Spike evidence")
    if not 0 < int(metrics["cycles"]) < 2**64:
        raise ValueError("invalid completed cycle count")
    if record["output_bytes_compared"] != 1000 or len(output) != 1000 or hashlib.sha256(output).hexdigest() != expected_hash or record["output_sha256"] != expected_hash:
        raise ValueError("incomplete or incorrect full output")
    if record["cpi"] != {"numerator": metrics["cycles"], "denominator": metrics["instructions"]}:
        raise ValueError("inconsistent CPI")
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--project", default="code/arch_project-custom")
    parser.add_argument("--run-label", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results/cvw/full-custom")
    parser.add_argument("--contract", type=Path, default=Path(__file__).with_name("custom_workloads.json"))
    parser.add_argument("--configurations", nargs="+", choices=("X1", "X2", "X3"), default=("X1", "X2"))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.run_label):
        parser.error("invalid run label")
    project = Path(args.project)
    if project.is_absolute() or ".." in project.parts:
        parser.error("project must remain inside the WSL home")
    script = f"python3 - <<'CVW_COLLECT'\nimport base64,hashlib,json\nfrom pathlib import Path\nroot=Path.home()/{args.project!r}\nlabel={args.run_label!r}\n"
    overlay_names = {"X1": "xqmac8", "X2": "xrequant", "X3": "xpostinc"}
    script += f"configurations={[(name, overlay_names[name]) for name in args.configurations]!r}\n"
    script += """
def read(path):
    return json.loads(path.read_text()) if path.exists() else None
def tail(path):
    return path.read_text(errors='replace').splitlines()[-18:] if path.exists() else []
suite = read(root / f'build/cvw/runs/custom-{label}.json')
suite_cmd = Path('/proc') / str(suite['supervisor_pid']) / 'cmdline' if suite else None
suite_alive = bool(suite_cmd and suite_cmd.exists() and any(script in suite_cmd.read_bytes() for script in (b'run_custom_suite.sh', b'run_postinc_suite.sh')))
result={'runs':{},'suite':suite,'suite_alive':suite_alive,'suite_tail':tail(root / f'build/cvw/runs/windows-{label}.log')}
for name,overlay_name in configurations:
    directory=root / f'build/cvw/runs/{name}-{label}'
    record=read(directory/'run.json')
    if record and record['status']=='RUNNING':
        cmd=Path('/proc') / str(record.get('runner_pid',0)) / 'cmdline'
        if not cmd.exists() or (name+'-'+label).encode() not in cmd.read_bytes():
            record=read(directory/'run.json')
            if record['status']=='RUNNING': record=dict(record,status='INTERRUPTED')
    value={'record':record,'progress_lines':[line for line in tail(directory/'simulation.log') if line.startswith('PROJECT ')], 'log_tail':tail(directory/'simulation.log'), 'launch_tail':tail(root/f'build/cvw/runs/{name}-{label}-launch.log'), 'smoke':read(root/f'build/cvw/runs/{name}-{label}-smoke/verification.json'), 'smoke_tail':tail(root/f'build/cvw/runs/{name}-{label}-smoke.log')}
    if record and record['status']=='PASS':
        binary=root/f'build/cvw/full-{overlay_name}/sim/verilator/wkdir/arch_project_{overlay_name}_testbench/Vtestbench'
        value['live_simulator_sha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
        value['output_base64']=base64.b64encode((directory/'output.bin').read_bytes()).decode()
    result['runs'][name]=value
print(json.dumps(result))
CVW_COLLECT
"""
    response = subprocess.run([sys.executable, str(ROOT / "tools/cvw_remote.py"), "--host", args.host], input=script, text=True, capture_output=True, check=True)
    snapshot = json.loads(response.stdout)
    contract_path = args.contract
    contract = json.loads(contract_path.read_text())
    contract_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    summary = {"schema_version": 1, "run_label": args.run_label, "collected_at_utc": datetime.now(timezone.utc).isoformat(), "runs": {}, "physical_clock_frequency": None, "area": None}
    for name, value in snapshot["runs"].items():
        record = value["record"]
        state = record["status"] if record else ("BUILDING" if snapshot["suite_alive"] else "FAIL")
        data = {"status": state, "checkpoint": contract[name]["checkpoint"], "progress_lines": value["progress_lines"], "smoke": value["smoke"], "cycles": None, "instructions": None, "evidence": "unavailable until complete verified inference"}
        if record:
            if record["contract_sha256"] != contract_hash or record["elf_sha256"] != contract[name]["elf_sha256"] or record["integration"]["extension"] != contract[name]["extension"]:
                raise ValueError("remote run provenance mismatch")
            data["integration"] = record["integration"]
        if state == "PASS":
            if record["simulator_sha256"] != value["live_simulator_sha256"]:
                raise ValueError("simulator changed after capture")
            smoke = value["smoke"]
            required_gates = {"correct", "wrong-count", "wrong-custom", "incomplete"}
            if name == "X3":
                required_gates.add("wrong-postinc")
            if not smoke or set(smoke["cases"]) != required_gates or any(case["status"] != "PASS" for case in smoke["cases"].values()):
                raise ValueError("missing preflight gates")
            output = base64.b64decode(value["output_base64"], validate=True)
            data.update(validate_pass(record, contract[name], contract["expected_output_sha256"], output), evidence="measured", output_bytes_compared=1000, elf_sha256=record["elf_sha256"], simulator_sha256=record["simulator_sha256"], wall_seconds=record["wall_seconds"])
        summary["runs"][name] = data
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    raw = ROOT / "build/cvw/remote" / args.run_label
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "snapshot.json").write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    lines = ["# Full-model custom-instruction RTL simulations", "", "Exact accepted checkpoint ELFs on separate pinned CV-Wally overlays. Final results require all 1,000 reference bytes, exact total and per-extension retirements, clean exit, and directed monitor gates.", "", "| Checkpoint | Status | Instructions | Cycles |", "|---|---|---:|---:|"]
    baseline = json.loads((ROOT / "results/cvw/baseline/summary.json").read_text())
    previous = ROOT / "results/cvw/full-custom/summary.json"
    if previous.exists() and args.output.resolve() != previous.parent.resolve():
        baseline["runs"].update(json.loads(previous.read_text())["runs"])
    for name, data in {**baseline["runs"], **summary["runs"]}.items():
        count = f"{int(data['instructions']):,}" if data["instructions"] else "pending"
        cycles = f"{int(data['cycles']):,}" if data["cycles"] else "pending"
        lines.append(f"| {name} | {data['status']} | {count} | {cycles} |")
    lines += ["", "Values are simulated cycles; physical clock frequency and area remain unmeasured. See [setup and reproduction](../../../docs/cvw-verilator.md#custom-instruction-full-inference) and [machine-readable evidence](summary.json).", ""]
    (args.output / "README.md").write_text("\n".join(lines))
    print(json.dumps({name: data["status"] for name, data in summary["runs"].items()}))


if __name__ == "__main__":
    main()
