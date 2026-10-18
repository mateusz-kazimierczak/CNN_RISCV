#!/usr/bin/env python3
"""Revalidate the combined custom RTL evidence and publish its measured scope."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "build/cvw/xrequant"
OVERLAY = ROOT / "build/cvw/wally-xrequant"
OUTPUT = ROOT / "results/cvw/xrequant"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    proof = json.loads((OUTPUT / "verification.json").read_text())
    integration = json.loads((OVERLAY / "integration.json").read_text())
    require(
        proof["status"] == "PASS" and proof["integration"] == integration,
        "RTL proof/overlay differs",
    )
    for name, sha in integration["patches_sha256"].items():
        require(digest(ROOT / name) == sha, f"patch changed: {name}")
    require(
        digest(ROOT / "tools/cvw/prepare_xrequant.py")
        == integration["generator_sha256"],
        "generator changed",
    )
    for name, sha in integration["files_sha256"].items():
        require(digest(OVERLAY / name) == sha, f"overlay changed: {name}")
    for name, configuration in integration["configurations"].items():
        require(
            digest(OVERLAY / "config" / name / "config.vh") == configuration["sha256"],
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
        "pinned Wally changed",
    )
    simulators = set()
    require(
        set(proof["builds"]) == set(integration["configurations"]),
        "missing configuration build",
    )
    for name, build in proof["builds"].items():
        require(
            json.loads((WORK / name / "build.json").read_text()) == build,
            f"build changed: {name}",
        )
        binary = WORK / name / "Vxrequant_soc_tb"
        require(digest(binary) == build["binary_sha256"], f"simulator changed: {name}")
        simulators.add(build["binary_sha256"])
        for path, sha in build["identity"]["inputs"].items():
            require(
                digest(OVERLAY / path if path == "integration.json" else ROOT / path)
                == sha,
                f"build input changed: {path}",
            )
    require(digest(WORK / "vectors.json") == proof["vectors_sha256"], "vectors changed")
    require(
        json.loads((WORK / "vectors.json").read_text())
        == json.loads((ROOT / "build/xrequant/tests/vectors.json").read_text()),
        "RTL vectors differ from original Spike/native ISA handoff",
    )
    require(
        proof["vectors"] == 12256
        and proof["random_vectors"] == 10000
        and proof["dependency_chain"] == 64,
        "vector coverage differs",
    )
    require(
        proof["descriptor_traps"] == 441 and proof["illegal_encodings"] == 1025,
        "trap coverage differs",
    )
    required = {
        "vectors",
        "vectors-stalled",
        "hazards",
        "hazards-stalled",
        "descriptor-traps",
        "descriptor-traps-stalled",
        "invalid-encodings",
        "qmac-hazards",
        "requant-only",
    }
    required.update(name + "-base" for name in proof["builds"])
    required.update(
        {
            "arch_project_xrequant-qmac",
            "arch_project_xrequant_off-qmac",
            "arch_project_xrequant_off-trap-0073128b",
            "arch_project_xrequant_only-trap-0073028b",
            "arch_project_xrequant_rv32-trap-0073128b",
            "arch_project_xrequant_rv32-trap-0073028b",
        }
    )
    require(required <= proof["cases"].keys(), "hardware cases missing")
    rows = []
    for name, case in sorted(proof["cases"].items()):
        log = WORK / (name + ".log")
        require(
            case["status"] == "PASS" and case["simulator_sha256"] in simulators,
            f"case failed: {name}",
        )
        require(
            digest(log) == case["log_sha256"]
            and digest(ROOT / case["elf"]) == case["elf_sha256"],
            f"case input/log changed: {name}",
        )
        text = log.read_text()
        match = re.search(r"XREQUANT_RTL_PASS (.*)", text)
        coverage = re.search(r"XREQUANT_COVERAGE (.*)", text)
        require(match and coverage, f"case did not finish: {name}")
        metrics = {
            key: int(value)
            for key, value in re.findall(r"(\w+)=(\d+)", match[1] + " " + coverage[1])
        }
        require(
            metrics == case["metrics"]
            and metrics["custom"] == metrics["qmac"] + metrics["requant"],
            f"counters differ: {name}",
        )
        rows.append({"case": name, **metrics})
    for name in ("hazards", "hazards-stalled"):
        metrics = proof["cases"][name]["metrics"]
        require(
            all(
                metrics[key] > 0
                for key in (
                    "req_forward_m",
                    "req_forward_w",
                    "req_load",
                    "req_mdu",
                    "req_csr",
                    "flushes",
                )
            ),
            "hazard coverage absent",
        )
    for name in ("descriptor-traps", "descriptor-traps-stalled"):
        require(
            proof["cases"][name]["metrics"]["descriptor_faults"] == 441,
            "precise descriptor trap coverage differs",
        )
    replay = proof["compiler_replay"]
    if replay:
        require("compiler-kernel-replay" in proof["cases"], "replay log missing")
        metrics = proof["cases"]["compiler-kernel-replay"]["metrics"]
        require(
            metrics["qmac"] == replay["qmac"]
            and metrics["requant"] == replay["requant"]
            and not metrics["traps"],
            "replay count reconciliation differs",
        )
        require(
            proof["cases"]["compiler-kernel-replay"]["elf_sha256"]
            == replay["elf_sha256"],
            "replay ELF differs",
        )
    summary = {
        "schema_version": 1,
        "status": "PASS",
        "wally_revision": integration["wally_revision"],
        "gates": {
            "isa_semantics": "PASS",
            "pipeline_hazards": "PASS",
            "precise_traps": "PASS",
            "independent_enables_rv32": "PASS",
            "xqmac8_regression": "PASS",
            "x2_kernel_replay": "PASS" if replay else "NOT_RUN",
            "full_model_rtl": "NOT_RUN",
            "physical_timing_area": "UNMEASURED",
        },
        "vectors": proof["vectors"],
        "random_vectors": proof["random_vectors"],
        "descriptor_traps": proof["descriptor_traps"],
        "illegal_encodings": proof["illegal_encodings"],
        "compiler_replay": replay,
        "cases": rows,
        "scope": "whole test-program cycles/retirements include initialization and checking; not full-inference performance or physical timing",
    }
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n"
    )
    lines = [
        "# CV-Wally Xrequant RTL verification",
        "",
        "Status: **PASS** for the recorded functional gates.",
        "",
        "The combined overlay executes Xqmac8 and exact two-stage Xrequant on the real pinned Wally SoC, with caches, forwarding and privilege/trap logic.",
        "",
        "12,256 oracle vectors (10,000 seeded random) plus 64 dependent requants pass in normal and externally stalled execution. 441 reserved-descriptor cases check mcause/mepc/mtval, unchanged destination/source registers and flushed younger custom/store operations, with ALU/load/MDU/CSR producers. All 1,025 neighboring encodings trap. Independent enables, RV32 traps and the original Xqmac8 vector/hazard suite pass.",
        "",
        "| Case | Xqmac8 | Xrequant | Traps | Program retirements | Program cycles |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case']} | {row['qmac']:,} | {row['requant']:,} | {row['traps']:,} | {row['retired']:,} | {row['cycles']:,} |"
        )
    if replay:
        lines += [
            "",
            f"X2 compiler replay: **{replay['fixtures']} fixtures**, nodes {', '.join(map(str, replay['nodes']))}, all {len(replay['cases'])} input scenarios. All **{replay['complete_output_bytes_compared']:,} output bytes** and guards compare exactly. **{replay['qmac']:,} Xqmac8** and **{replay['requant']:,} Xrequant** retirements reconcile with retained Spike evidence. The original linked replay ELF runs without recompilation.",
            "",
            f"Replay artifact: `{replay['artifact_id']}`.",
        ]
    lines += [
        "",
        "Cycles above cover whole test programs, including setup and checks. Full-model RTL inference performance and synthesis timing/area remain unmeasured.",
        "",
        "Reproduce: `gmake cvw-xrequant-checkpoint`.",
        "",
        "[Implementation and commands](../../../docs/cvw-xrequant.md) · [Full evidence](verification.json) · [Compact gates](summary.json)",
        "",
        "Executables, logs and vector export: ignored `build/cvw/xrequant/`. Original Xqmac8 and B0/B1 overlays are preserved.",
    ]
    (OUTPUT / "README.md").write_text("\n".join(lines) + "\n")
    print(OUTPUT / "summary.json")


if __name__ == "__main__":
    main()
