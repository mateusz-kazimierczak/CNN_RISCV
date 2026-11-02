#!/usr/bin/env python3
"""Validate the retained hardware-era sequence, or explicitly recapture it."""

from __future__ import annotations

import argparse
import sys

from hardware_experiments import (
    CAPTURES,
    MANIFEST,
    RESULTS,
    ROOT,
    flags,
    load_capture,
    read,
    require,
    stages,
    validate_selection,
    validate_transition,
)

from compiler.build_evidence import canonical, digest
from tools.run_software_experiments import call, verify_correctness

INDEX = RESULTS / "hardware-progression/captures.json"


def run(recapture=False, through="X5"):
    bundles, records = {}, []
    prior = read(INDEX) if INDEX.exists() else None
    reusable = (
        {r["stage"]: ROOT / r["summary"] for r in prior["stages"]}
        if prior and prior["manifest_sha256"] == digest(MANIFEST)
        else {}
    )
    for stage in stages():
        source = reusable.get(stage["id"], RESULTS / stage["source"] / "summary.json")
        available = (
            source.exists()
            and (CAPTURES / read(source)["capture_id"] / "manifest.json").exists()
        )
        if recapture or not available:
            generated = (
                ROOT / "build/compiler" / ("HW-" + stage["id"].replace(".", "-"))
            )
            checkpoint = "HW-" + stage["id"].replace(".", "-")
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
                *flags(stage),
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
                checkpoint,
                "--results-dir",
                RESULTS / checkpoint,
            ]
            if stage["parent"]:
                command.extend(["--parent", bundles[stage["parent"]]["directory"]])
            call(*command)
            verify_correctness(generated)
            if stage["config"] != "B1":
                call(
                    sys.executable,
                    "tools/xqmac8/full_input.py",
                    "--generated-dir",
                    generated,
                )
            candidate = RESULTS / checkpoint / "summary.json"
            if source.exists():
                require(
                    read(candidate)["inference"] == read(source)["inference"],
                    f"recapture differs from retained reference: {stage['id']}",
                )
            source = candidate
        bundle = load_capture(source)
        validate_selection(stage, bundle)
        if stage["parent"]:
            validate_transition(stage, bundles[stage["parent"]], bundle)
        bundles[stage["id"]] = bundle
        records.append(
            {
                "stage": stage["id"],
                "summary": str(source.relative_to(ROOT)),
                "summary_sha256": digest(source),
                "capture_id": bundle["summary"]["capture_id"],
            }
        )
        print(
            f"Validated {stage['id']}: {bundle['summary']['inference']['instructions']['value']} instructions",
            flush=True,
        )
        if stage["id"] == through:
            break
    INDEX.parent.mkdir(exist_ok=True)
    INDEX.write_text(
        canonical(
            {
                "schema_version": 1,
                "manifest_sha256": digest(MANIFEST),
                "complete": through == "X5",
                "stages": records,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument(
        "--recapture",
        action="store_true",
        help="generate separate fresh builds/captures; preserved results stay intact",
    )
    parser.add_argument("--through", choices=[s["id"] for s in stages()], default="X5")
    args = parser.parse_args()
    if args.plan:
        for stage in stages():
            print(canonical({**stage, "flags": flags(stage)}), end="")
            if stage["id"] == args.through:
                break
    else:
        run(args.recapture, args.through)


if __name__ == "__main__":
    main()
