#!/usr/bin/env python3
"""Authenticate saved Xpostinc RTL evidence and publish a compact report."""

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
WORK = ROOT / "build/cvw/xpostinc"
OVERLAY = ROOT / "build/cvw/wally-xpostinc"
OUTPUT = ROOT / "results/cvw/xpostinc"


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
        digest(ROOT / "tools/cvw/prepare_xpostinc.py")
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
    require(
        set(proof["builds"]) == set(integration["configurations"]),
        "missing configuration build",
    )
    simulators = set()
    for name, build in proof["builds"].items():
        require(
            json.loads((WORK / name / "build.json").read_text()) == build,
            f"build changed: {name}",
        )
        require(
            digest(WORK / name / "Vxpostinc_soc_tb") == build["binary_sha256"],
            f"simulator changed: {name}",
        )
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
        == json.loads((ROOT / "build/xpostinc/tests/vectors.json").read_text()),
        "RTL vectors differ from Spike handoff",
    )
    require(
        proof["vectors"] == 12672
        and proof["vector_retirements"] == 12683
        and proof["faults"] == 35,
        "coverage differs",
    )
    from tools.xpostinc.contract import LOADS, STORES

    required = {
        "hazards",
        "hazards-stalled",
        "ordinary-misaligned",
        "vm-success",
        "qmac-regression",
        "requant-regression",
        "qmac-hazards",
        "requant-hazards",
        "copy-microbenchmark",
        "postinc-only-illegal-0073028b",
        "postinc-only-illegal-0073128b",
    }
    required.update(name + "-base" for name in proof["builds"])
    for config in ("arch_project_xpostinc", "arch_project_xpostinc_only"):
        required.update(config + "-vectors" + suffix for suffix in ("", "-stalled"))
    for op in (*LOADS, *STORES):
        required.update(op + "-access" + suffix for suffix in ("", "-stalled"))
        required.add("vm-page-fault-" + op)
        for config in ("arch_project_xpostinc_off", "arch_project_xpostinc_rv32"):
            required.add(config + "-" + op)
    for producer in ("add", "load", "mul", "div", "csr"):
        required.update(
            "fault-producer-" + producer + "-" + op for op in ("xldpi", "xsdpi")
        )
    required.update("vm-alignment-priority-" + op for op in ("xldpi", "xsdpi"))
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
        lines = re.findall(
            r"(?:XPOSTINC_RTL_PASS|XPOSTINC_COVERAGE|XPOSTINC_HAZARDS|XREQUANT_COVERAGE) (.*)",
            text,
        )
        require(len(lines) == 4, f"case incomplete: {name}")
        metrics = {
            key: int(value)
            for key, value in re.findall(r"(\w+)=(\d+)", " ".join(lines))
        }
        require(
            metrics == case["metrics"]
            and metrics["custom"]
            == sum(metrics[k] for k in ("qmac", "requant", "postload", "poststore")),
            f"counters differ: {name}",
        )
        rows.append({"case": name, **metrics})
    for name in ("hazards", "hazards-stalled"):
        require(
            all(
                proof["cases"][name]["metrics"][key] > 0
                for key in (
                    "base_a_m",
                    "base_a_w",
                    "base_b_m",
                    "base_b_w",
                    "base_c_m",
                    "base_c_w",
                )
            ),
            "base forwarding coverage absent",
        )
    replay = proof["compiler_replay"]
    if replay:
        from tools.investigation.replay import verify_replay

        case = proof["cases"]["compiler-kernel-replay"]
        directory, _, workload, _ = verify_replay((ROOT / case["elf"]).parent.parent)
        require(
            directory.name == replay["artifact_id"]
            and workload["configuration"] == "X3",
            "replay identity differs",
        )
        require(case["elf_sha256"] == replay["elf_sha256"], "replay ELF differs")
        actual = [
            json.loads(line)
            for line in (WORK / "compiler-kernel-replay.log").read_text().splitlines()
            if line.startswith('{"fixture":')
        ]
        require(
            len(actual) == len(workload["fixtures"]) == replay["fixtures"],
            "incomplete replay",
        )
        for index, (row, fixture) in enumerate(zip(actual, workload["fixtures"])):
            require(
                row
                == {
                    "fixture": index,
                    "status": fixture["expected_status"],
                    "guards": True,
                    "bytes_compared": fixture["output"]["bytes"],
                    "first_difference": None,
                },
                f"replay mismatch: {index}",
            )
        require(
            all(
                case["metrics"][key] == value for key, value in replay["counts"].items()
            )
            and not case["metrics"]["traps"],
            "replay retirement differs",
        )
    summary = {
        "schema_version": 1,
        "status": "PASS",
        "wally_revision": integration["wally_revision"],
        "gates": {
            "isa_semantics": "PASS",
            "dual_result_hazards_and_flushes": "PASS",
            "precise_faults": "PASS",
            "sv39_translation_and_page_faults": "PASS",
            "natural_alignment_with_zicclsm": "PASS",
            "independent_enables_rv32": "PASS",
            "xqmac8_xrequant_regressions": "PASS",
            "compiler_replay": "PASS" if replay else "NOT_RUN",
            "full_inference_cycles": "NOT_MEASURED",
            "physical_timing_area": "NOT_MEASURED",
        },
        "vectors": proof["vectors"],
        "vector_retirements": proof["vector_retirements"],
        "fault_fixtures": proof["faults"],
        "rtl_programs": len(rows),
        "configurations": len(proof["builds"]),
        "compiler_replay": replay,
        "verification_sha256": digest(OUTPUT / "verification.json"),
        "scope": proof["scope"],
    }
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    with (OUTPUT / "cases.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Xpostinc on CV-Wally",
        "",
        f"**PASS**: {len(rows)} self-checking program runs on six real Wally SoC configurations.",
        "",
        "- 12,672 identical Spike/RTL vectors; 12,683 memory retirements per vector run.",
        "- 35 fault fixtures with normal/stalled execution, unchanged registers and guarded RAM.",
        "- Dual-result forwarding, dependent loads/stores, aliases, x0, and branch/trap flushes.",
        "- Sv39 TLB miss success, page faults, and alignment priority over unmapped pages.",
        "- Mandatory custom alignment with Zicclsm enabled; ordinary misaligned accesses still work.",
        "- Independent enables, RV32 rejection, base/M/C compatibility and earlier custom regressions.",
    ]
    if replay:
        lines += [
            f"- Original verified X3 compiler ELF: {replay['fixtures']} complete fixtures, {replay['complete_output_bytes_compared']:,} output bytes and guards compared.",
            f"- Replay retirements: {replay['counts']['postload']:,} post-increment loads, {replay['counts']['poststore']:,} stores; zero unexpected traps.",
        ]
    lines += [
        "",
        "[Detailed evidence](verification.json), [authenticated summary](summary.json), [per-program counts](cases.csv).",
        "",
        "Reproduce with `gmake cvw-xpostinc-checkpoint`; see [implementation and setup](../../../docs/cvw-xpostinc.md).",
        "",
        "Cycles in cases.csv include setup, console and self-checks. Full-inference cycles and physical timing/area are unmeasured. Source, simulator, ELF and log hashes are authenticated by `python3 tools/cvw/xpostinc/report.py`; retain the ignored build evidence.",
        "",
    ]
    (OUTPUT / "README.md").write_text("\n".join(lines))
    print(f"Xpostinc CV-Wally report: PASS ({len(rows)} programs)")


if __name__ == "__main__":
    main()
