#!/usr/bin/env python3
"""Build, verify and profile the cumulative software sequence from one manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from compiler.build_evidence import canonical, digest
from tools.build_a0 import verify_build
from tools.profile_compiler import make_summary, verify_capture

MANIFEST = ROOT / "experiments/software.json"
RESULTS = ROOT / "results/profiling"
CAPTURES = ROOT / "build/profiling/compiler"


def stages():
    spec = json.loads(MANIFEST.read_text())
    flags = []
    result = []
    for stage in spec["stages"]:
        for flag in stage["add_flags"]:
            if flag == "$inline_nodes":
                flags.extend(map(str, spec["inline_nodes"]))
            else:
                flags.append(flag)
        result.append({**stage, "flags": list(flags)})
    return result


def call(*args):
    command = [str(a) for a in args]
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def verify_correctness(generated):
    """Check the saved differential runs belong to these exact live builds."""
    golden_path = ROOT / "tests/compiler/fixtures/oracle-golden.json"
    golden = json.loads(golden_path.read_text())
    verified = {"oracle_golden_sha256": digest(golden_path), "builds": []}
    for kind in ("native", "capture", "sanitized"):
        build = verify_build(generated, kind)
        path = generated / kind / "differential.json"
        report = json.loads(path.read_text())
        if (
            report["status"] != "PASS"
            or report["binary_sha256"] != build["binary_sha256"]
            or report["configuration"] != build["configuration"]
            or report["kind"] != kind
        ):
            raise ValueError(f"incorrect or stale differential report: {path}")
        if len(report["cases"]) != len(golden["cases"]):
            raise ValueError(f"incomplete differential cases: {path}")
        cases = []
        for case, expected in zip(report["cases"], golden["cases"]):
            status = 2 if expected["expected_signal"] else 0
            nodes = 0 if kind == "native" else expected["expected_nodes"]
            if (
                case["name"] != expected["name"]
                or case["status"] != status
                or case["nodes_compared"] != nodes
            ):
                raise ValueError(f"differential coverage differs: {path}")
            for filename, sha in case["files"].items():
                artifact = generated / kind / "captures" / case["name"] / filename
                if digest(artifact) != sha:
                    raise ValueError(f"differential output changed: {artifact}")
            if (
                not status
                and case["files"].get("output.bin") != expected["output_sha256"]
            ):
                raise ValueError(f"output differs from pinned oracle: {path}")
            cases.append({k: case[k] for k in ("name", "status", "nodes_compared")})
        verified["builds"].append(
            {
                "kind": kind,
                "binary_sha256": build["binary_sha256"],
                "differential_sha256": digest(path),
                "cases": cases,
            }
        )
    return verified


def run_stage(stage, parent, resume):
    name = stage["checkpoint"]
    generated = ROOT / "build/compiler" / name
    result = RESULTS / name
    receipt_path = result / "experiment.json"
    selection = {
        "manifest_sha256": digest(MANIFEST),
        "stage": stage,
        "parent_capture_id": parent,
    }
    if resume and receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt["selection"] == selection:
            # A label or old summary is insufficient: verify live build inputs,
            # frozen capture, all correctness receipts and parent identity.
            verify_correctness(generated)
            verify_build(generated, "rv64")
            capture = CAPTURES / receipt["capture_id"]
            verified = verify_capture(capture)
            summary = make_summary(capture, verified)
            if summary != json.loads((result / "summary.json").read_text()):
                raise ValueError(f"saved summary changed: {name}")
            if parent:
                if (
                    json.loads((capture / "parent-summary.json").read_text())[
                        "capture_id"
                    ]
                    != parent
                ):
                    raise ValueError(
                        "resume parent differs from selected previous stage"
                    )
                if (capture / "parent-identity.txt").read_text().strip() != digest(
                    CAPTURES / parent / "manifest.json"
                ):
                    raise ValueError("resume parent identity changed")
            print(
                f"Reusing validated {stage['id']}: {receipt['capture_id']}", flush=True
            )
            return receipt["capture_id"]
    call(
        sys.executable,
        "-m",
        "compiler",
        "generate",
        ROOT / "models/efficientnet-lite0-int8.tflite",
        "--config",
        stage["config"],
        "--output-dir",
        generated,
        *stage["flags"],
    )
    for kind in ("native", "capture", "sanitized", "rv64"):
        call(
            sys.executable,
            "tools/build_a0.py",
            "build",
            "--kind",
            kind,
            "--generated-dir",
            generated,
        )
        if kind != "rv64":
            call(
                sys.executable,
                "tools/build_a0.py",
                "compare",
                "--kind",
                kind,
                "--generated-dir",
                generated,
            )
    command = [
        sys.executable,
        "tools/profile_compiler.py",
        "run",
        "--build-manifest",
        generated / "rv64/build.json",
        "--checkpoint",
        name,
        "--results-dir",
        result,
    ]
    if parent:
        command.extend(["--parent", CAPTURES / parent])
    # This performs ordinary Spike correctness followed by two exact profiles.
    call(*command)
    summary = json.loads((result / "summary.json").read_text())
    receipt_path.write_text(
        canonical(
            {
                "selection": selection,
                "capture_id": summary["capture_id"],
                "correctness": "native, captured intermediates, sanitizers, ordinary Spike and two identical profiles",
            }
        )
    )
    return summary["capture_id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--through", choices=[s["id"] for s in stages()], default="B1.7"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse only validated unchanged completed stages",
    )
    parser.add_argument(
        "--plan", action="store_true", help="print fully expanded cumulative selections"
    )
    args = parser.parse_args()
    parent = None
    for stage in stages():
        if args.plan:
            print(canonical(stage), end="")
        else:
            parent = run_stage(stage, parent, args.resume)
        if stage["id"] == args.through:
            break


if __name__ == "__main__":
    main()
