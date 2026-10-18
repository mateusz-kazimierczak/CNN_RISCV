#!/usr/bin/env python3
"""Revalidate saved hardware evidence and publish a compact Xqmac8 RTL report."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "build/cvw/xqmac8"
OVERLAY = ROOT / "build/cvw/wally-xqmac8"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    path = ROOT / "results/cvw/xqmac8/verification.json"
    proof = json.loads(path.read_text())
    require(proof["status"] == "PASS", "hardware tests have not passed")
    integration = json.loads((OVERLAY / "integration.json").read_text())
    require(proof["integration"] == integration, "overlay identity changed")
    require(
        digest(ROOT / "rtl/cvw/xqmac8.patch") == integration["patch_sha256"],
        "RTL patch changed",
    )
    require(
        digest(ROOT / "tools/cvw/prepare_xqmac8.py") == integration["generator_sha256"],
        "overlay generator changed",
    )
    for name, expected in integration["files_sha256"].items():
        require(digest(OVERLAY / name) == expected, f"overlay source changed: {name}")
    for name, value in integration["configurations"].items():
        require(
            digest(OVERLAY / "config" / name / "config.vh") == value["sha256"],
            f"configuration changed: {name}",
        )
    source = ROOT / ".deps/cvw"
    require(
        subprocess.check_output(
            ["git", "-C", source, "rev-parse", "HEAD"], text=True
        ).strip()
        == integration["wally_revision"],
        "Wally revision changed",
    )
    require(
        not subprocess.check_output(["git", "-C", source, "diff", "HEAD", "--"]),
        "pinned Wally sources changed",
    )
    simulators = set()
    for name, build in proof["builds"].items():
        require(
            json.loads((WORK / name / "build.json").read_text()) == build,
            f"build record changed: {name}",
        )
        binary = WORK / name / "Vxqmac8_soc_tb"
        require(digest(binary) == build["binary_sha256"], f"simulator changed: {name}")
        simulators.add(build["binary_sha256"])
        for name, expected in build["identity"]["inputs"].items():
            actual = OVERLAY / name if name == "integration.json" else ROOT / name
            require(digest(actual) == expected, f"build input changed: {name}")
    vectors = WORK / "vectors.json"
    require(digest(vectors) == proof["vectors_sha256"], "hardware vectors changed")
    # These are the existing independent ISA handoff vectors, not expectations
    # recalculated from RTL. Compare the retained Spike export when available.
    spike_vectors = ROOT / "build/xqmac8/tests/vectors.json"
    if spike_vectors.exists():
        require(
            json.loads(spike_vectors.read_text()) == json.loads(vectors.read_text()),
            "RTL and original ISA handoff vectors differ",
        )
    require(
        proof["vectors"] == 10852
        and proof["random_vectors"] == 10000
        and proof["illegal_encodings"] == 1026,
        "coverage changed",
    )
    rows = []
    for name, case in proof["cases"].items():
        log = WORK / (name + ".log")
        require(
            case["status"] == "PASS" and case["simulator_sha256"] in simulators,
            f"invalid case: {name}",
        )
        require(digest(log) == case["log_sha256"], f"test log changed: {name}")
        match = re.search(r"XQMAC8_RTL_PASS (.*)", log.read_text())
        require(match is not None, f"incomplete simulation: {name}")
        values = {
            key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", match[1])
        }
        require(values == case["metrics"], f"metrics differ from simulation: {name}")
        require(
            digest(case["command"][0]) == case["simulator_sha256"],
            f"case simulator changed: {name}",
        )
        rows.append({"case": name, **values})
    for name in ("hazards", "hazards-stalled"):
        values = proof["cases"][name]["metrics"]
        require(
            values["custom"] == 1070
            and all(
                values[k] > 0
                for k in (
                    "forward_m",
                    "forward_w",
                    "oldrd_load",
                    "oldrd_mdu",
                    "oldrd_csr",
                    "flushes",
                )
            ),
            "dependency coverage missing",
        )
    replay = proof.get("compiler_replay")
    if replay:
        require(
            replay["nodes"] == [4, 58]
            and len(replay["cases"]) == 8
            and replay["fixtures"] == 20
            and replay["custom_instructions"] == 39338026,
            "compiler replay coverage changed",
        )
        require(
            proof["cases"]["compiler-kernel-replay"]["metrics"]["custom"]
            == replay["custom_instructions"],
            "compiler custom counts differ",
        )
    summary = {
        "schema_version": 1,
        "status": "PASS",
        "extension": "Xqmac8-v1",
        "wally_revision": integration["wally_revision"],
        "patch_sha256": integration["patch_sha256"],
        "verification_sha256": digest(path),
        "vectors": proof["vectors"],
        "random_vectors": 10000,
        "illegal_encodings": 1026,
        "cases": rows,
        "compiler_replay": replay,
        "gates": {
            "isa_semantics": "PASS",
            "pipeline_dependencies": "PASS",
            "trap_precision": "PASS",
            "rv32_and_disabled_traps": "PASS",
            "base_isa_and_misa": "PASS",
            "compiler_kernel_replay": "PASS" if replay else "NOT_RUN",
            "full_model_cycles": "NOT_RUN",
            "synthesis_timing_area": "BLOCKED: matched synthesis manifest pending",
        },
    }
    output = path.parent / "summary.json"
    output.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    lines = [
        "# CV-Wally Xqmac8 RTL verification",
        "",
        "Status: **PASS** for the recorded functional hardware gates.",
        "",
        f"Pinned Wally: `{integration['wally_revision']}`. Original checkout and B0/B1 overlay remain unchanged.",
        "",
        "The real Wally SoC executes 10,852 oracle vectors (10,000 seeded random), normal/stalled dependency programs,",
        "1,026 invalid encodings, RV32/disabled-extension traps and base-ISA/misa compatibility checks.",
        "",
        "| Case | Custom retirements | Traps | Program retirements | Program cycles |",
        "|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {r['case']} | {r['custom']:,} | {r['traps']:,} | {r['retired']:,} | {r['cycles']:,} |"
        for r in rows
    ]
    if replay:
        lines += [
            "",
            f"Compiler replay: **{replay['fixtures']} fixtures**, complete nodes 4/58 across all eight scenarios plus four raw-dot controls.",
            f"All **{replay['complete_output_bytes_compared']:,} output bytes** compare exactly, including guards;",
            f"**{replay['custom_instructions']:,} custom retirements** reconcile with the retained Spike profile.",
            f"Replay artifact: `{replay['artifact_id']}`.",
        ]
    lines += [
        "",
        "Cycles above cover entire test programs, initialization and checking. They are not full-inference cycles or a physical clock-frequency result.",
        "Full-model X1 performance and matched synthesis area/timing remain separate, unmeasured gates.",
        "",
        "Reproduce: `gmake cvw-xqmac8-checkpoint`.",
        "",
        "[Implementation and commands](../../../docs/cvw-xqmac8.md) · [Full verification](verification.json) · [Compact gates](summary.json)",
        "",
        "Raw logs, executables and memory images are retained under ignored `build/cvw/xqmac8/`.",
    ]
    (path.parent / "README.md").write_text("\n".join(lines) + "\n")
    print(output)


if __name__ == "__main__":
    main()
