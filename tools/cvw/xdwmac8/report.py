#!/usr/bin/env python3
"""Authenticate the saved bank RTL, programs, counters and original compiler ELF."""

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from tools.cvw.xdwmac8.runtime import WORK, OVERLAY, digest
from tools.xdwmac8.contract import NAMES

OUTPUT = ROOT / "results/cvw/xdwmac8"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    proof = json.loads((OUTPUT / "verification.json").read_text())
    extra_path = WORK / "integration-tests.json"
    extra = json.loads(extra_path.read_text())
    require(extra["status"] == "PASS", "consumer/LSU integration tests incomplete")
    for name, sha in extra["source_sha256"].items():
        require(digest(ROOT / name) == sha, f"integration-test source changed {name}")
    require(
        not (proof["cases"].keys() & extra["cases"].keys()),
        "duplicate hardware case identity",
    )
    proof["cases"] = {**proof["cases"], **extra["cases"]}
    integration = json.loads((OVERLAY / "integration.json").read_text())
    require(
        proof["status"] == "PASS" and proof["integration"] == integration,
        "overlay/proof mismatch",
    )
    for name, sha in integration["patches_sha256"].items():
        require(digest(ROOT / name) == sha, f"patch changed {name}")
    require(
        digest(ROOT / "tools/cvw/prepare_xdwmac8.py")
        == integration["generator_sha256"],
        "generator changed",
    )
    require(
        digest(ROOT / "tools/xdwmac8/contract.py")
        == integration["bank_contract_sha256"],
        "ISA contract changed",
    )
    for name, sha in integration["files_sha256"].items():
        require(digest(OVERLAY / name) == sha, f"overlay changed {name}")
    for name, config in integration["configurations"].items():
        require(
            digest(OVERLAY / "config" / name / "config.vh") == config["sha256"],
            f"configuration changed {name}",
        )
    require(
        subprocess.check_output(
            ["git", "-C", ROOT / ".deps/cvw", "rev-parse", "HEAD"], text=True
        ).strip()
        == integration["wally_revision"],
        "pinned revision changed",
    )
    require(
        not subprocess.check_output(
            ["git", "-C", ROOT / ".deps/cvw", "diff", "HEAD", "--"]
        ),
        "pinned sources changed",
    )
    require(
        set(proof["builds"]) == set(integration["configurations"]),
        "configuration coverage incomplete",
    )
    simulators = set()
    for name, build in proof["builds"].items():
        require(
            json.loads((WORK / name / "build.json").read_text()) == build,
            f"build record changed {name}",
        )
        require(
            digest(WORK / name / "Vxdwmac8_soc_tb") == build["binary_sha256"],
            f"simulator changed {name}",
        )
        simulators.add(build["binary_sha256"])
        for path, sha in build["identity"]["inputs"].items():
            require(
                digest(OVERLAY / path if path == "integration.json" else ROOT / path)
                == sha,
                f"build source changed {path}",
            )
    for name, sha in proof["source_sha256"].items():
        require(digest(ROOT / name) == sha, f"test source changed {name}")
    unit = proof["unit"]
    require(
        unit["status"] == "PASS"
        and digest(WORK / "unit/Vbank_tb") == unit["simulator_sha256"]
        and digest(WORK / "unit.log") == unit["log_sha256"],
        "unit proof changed",
    )
    require(
        "XDWMAC8_BANK_UNIT_PASS instances=2 warm_reset=1 pending_reset=1 stall=1 trap_flush=1"
        in (WORK / "unit.log").read_text(),
        "unit gates incomplete",
    )
    overlaylog = WORK / "overlay-tests.log"
    require(
        re.search(r"Ran 5 tests", overlaylog.read_text())
        and re.search(r"^OK$", overlaylog.read_text(), re.M),
        "overlay tests incomplete",
    )
    handoff = ROOT / "build/xdwmac8/tests"
    require(
        proof["vectors"] == 10256
        and digest(handoff / "vectors.json") == proof["vectors_sha256"],
        "Spike vector handoff changed",
    )
    vector_proof = json.loads((handoff / "verification.json").read_text())
    require(
        vector_proof["status"] == "PASS"
        and vector_proof["counts"] == proof["vector_counts"]
        and vector_proof["elf_sha256"] == digest(handoff / "vectors.elf"),
        "vector ELF/counts differ from Spike",
    )
    required = {
        "hazards",
        "hazards-stalled",
        "qmac-regression",
        "requant-regression",
        "postinc-regression",
        "qmac-hazards",
        "requant-hazards",
        "postinc-hazards",
        "privilege-s",
        "privilege-u",
    }
    for config in ("arch_project_xdwmac8", "arch_project_xdwmac8_only"):
        required.update(config + "-vectors" + s for s in ("", "-stalled"))
    for config in ("arch_project_xdwmac8_off", "arch_project_xdwmac8_rv32"):
        required.update(config + "-" + name for name in NAMES)
    required.update(name + "-base" for name in proof["builds"])
    required.update(f"reserved-{i}" + s for i in range(8) for s in ("", "-stalled"))
    required.update(
        "irq-" + name + s for name in ("xdwmac8", "xdwset2") for s in ("", "-stalled")
    )
    required.update(
        "fault-" + kind + "-" + op
        for kind in ("load", "store", "ecall", "descriptor")
        for op in ("mac", "set")
    )
    required.update(
        f"bank-only-illegal-{value:08x}" for value in (0xB, 0x100B, 0x2B, 0x7B)
    )
    required.update(
        {"get-consumers", "get-consumers-stalled", "irq-get", "irq-get-stalled"}
    )
    required.update(
        "integration-" + kind + "-" + op
        for kind in ("load", "postload", "poststore", "postalign")
        for op in ("mac", "set")
    )
    require(required <= proof["cases"].keys(), "RTL coverage incomplete")
    rows = []
    for name, case in sorted(proof["cases"].items()):
        require(
            case["status"] == "PASS" and case["simulator_sha256"] in simulators,
            f"case failed {name}",
        )
        log = WORK / (name + ".log")
        require(
            digest(log) == case["log_sha256"]
            and digest(ROOT / case["elf"]) == case["elf_sha256"],
            f"case artifacts changed {name}",
        )
        text = log.read_text()
        lines = re.findall(
            r"(?:XDWMAC8_RTL_PASS|XREQUANT_COVERAGE|XPOSTINC_COVERAGE|XPOSTINC_HAZARDS|XDWMAC8_COVERAGE) (.*)",
            text,
        )
        metrics = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", " ".join(lines))}
        require(
            len(lines) == 5 and metrics == case["metrics"],
            f"case counters changed {name}",
        )
        require(
            metrics["custom"]
            == sum(
                metrics[k]
                for k in (
                    "qmac",
                    "requant",
                    "postload",
                    "poststore",
                    "dwmac",
                    *(f"dwset{i}" for i in range(4)),
                    *(f"dwget{i}" for i in range(4)),
                )
            ),
            f"custom counts disagree {name}",
        )
        rows.append({"case": name, **metrics})
    for name in ("hazards", "hazards-stalled"):
        require(
            all(
                proof["cases"][name]["metrics"][k] > 0
                for k in (
                    "bank_forward",
                    "dw_forward_m",
                    "dw_forward_w",
                    "dw_load",
                    "dw_mdu",
                    "dw_csr",
                    "base_a_m",
                )
            ),
            "dependency coverage missing",
        )
    for name in (
        "irq-xdwmac8",
        "irq-xdwmac8-stalled",
        "irq-xdwset2",
        "irq-xdwset2-stalled",
    ):
        require(
            proof["cases"][name]["metrics"]["bank_trap"] > 0
            and proof["cases"][name]["metrics"]["irq"] == 1,
            "interrupt did not suppress pending bank write",
        )
    for name in ("get-consumers", "get-consumers-stalled"):
        require(
            all(
                proof["cases"][name]["metrics"][k] > 0
                for k in ("forward_m", "forward_w", "req_forward_m", "req_forward_w")
            ),
            "get-result forwarding coverage absent",
        )
    for kind in ("load", "postload", "poststore", "postalign"):
        for op in ("mac", "set"):
            require(
                proof["cases"]["integration-" + kind + "-" + op]["metrics"][
                    "bank_flush"
                ]
                > 0,
                "younger bank update was not exercised at the memory fault",
            )
    replay = proof["compiler_replay"]
    if replay:
        from tools.investigation.replay import verify_replay

        case = proof["cases"]["compiler-kernel-replay"]
        directory, _, workload, _ = verify_replay((ROOT / case["elf"]).parent.parent)
        require(
            directory.name == replay["artifact_id"]
            and workload["configuration"] == "X4"
            and case["elf_sha256"] == replay["elf_sha256"],
            "replay identity mismatch",
        )
        actual = [
            json.loads(line)
            for line in (WORK / "compiler-kernel-replay.log").read_text().splitlines()
            if line.startswith('{"fixture":')
        ]
        require(
            len(actual) == len(workload["fixtures"]) == replay["fixtures"],
            "incomplete replay",
        )
        for i, (row, f) in enumerate(zip(actual, workload["fixtures"])):
            require(
                row
                == {
                    "fixture": i,
                    "status": f["expected_status"],
                    "guards": True,
                    "bytes_compared": f["output"]["bytes"],
                    "first_difference": None,
                },
                f"replay output mismatch {i}",
            )
        for name, count in replay["bank_counts"].items():
            require(
                case["metrics"]["dwmac" if name == "xdwmac8" else name[1:]] == count,
                f"bank retirements mismatch {name}",
            )
        require(
            all(
                case["metrics"][name] == count
                for name, count in replay["counts"].items()
            )
            and not case["metrics"]["traps"],
            "earlier custom count mismatch in replay",
        )
    summary = {
        "schema_version": 1,
        "status": "PASS",
        "wally_revision": integration["wally_revision"],
        "program_runs": len(rows),
        "configurations": len(proof["builds"]),
        "vectors": proof["vectors"],
        "bank_vector_retirements": sum(proof["vector_counts"].values()),
        "gates": {
            "arithmetic_and_transfers": "PASS",
            "shared_multiplier_regressions": "PASS",
            "bank_and_GPR_hazards": "PASS",
            "stall_flush_and_precise_exceptions": "PASS",
            "targeted_interrupt_save_restore": "PASS",
            "independent_instances_and_warm_reset": "PASS",
            "disabled_RV32_independent_enables": "PASS",
            "S_U_access": "PASS",
            "overlay_ownership_and_decode": "PASS",
            "compiler_replay": "PASS" if replay else "NOT_RUN",
            "full_inference_cycles": "NOT_MEASURED",
            "physical_timing_area": "NOT_MEASURED",
        },
        "compiler_replay": replay,
        "verification_sha256": digest(OUTPUT / "verification.json"),
        "integration_tests_sha256": digest(extra_path),
        "overlay_test_log_sha256": digest(overlaylog),
        "report_source_sha256": digest(Path(__file__)),
        "scope": proof["scope"],
    }
    (OUTPUT / "integration-tests.json").write_bytes(extra_path.read_bytes())
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    with (OUTPUT / "cases.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Eight-lane depthwise bank on CV-Wally",
        "",
        f"**PASS**: {len(rows)} self-checking program runs on five real Wally SoC configurations.",
        "",
        "- 10,256 identical Spike/RTL arithmetic vectors; 92,399 bank operations per vector run, with normal and stalled execution on combined and bank-only cores.",
        "- Eight signed-byte multipliers are shared with Xqmac8; the bank independently accumulates all eight INT32 lanes.",
        "- Pending-bank and GPR forwarding, load/MDU/CSR producers, post-increment primary/base consumers, x0 and aliases.",
        "- Get-result consumers include ALU, branch, ordinary and post-increment memory, Xqmac8 old-rd, and Xrequant with M/W forwarding.",
        "- Eight reserved encodings, every disabled/RV32 instruction, independent enables, and base/M/C compatibility.",
        "- Older load/store/descriptor/ecall faults and wrong-path operations preserve bank state.",
        "- Targeted M-stage MAC/set interrupts preserve the bank; explicit handler save/overwrite/restore and reexecution pass normally and under stalls.",
        "- Two independent instances, warm reset with pending operations, S/U bank access, and earlier Xqmac8/Xrequant/Xpostinc vector and hazard regressions.",
        "- Five overlay ownership/isolation/decode tests pass.",
    ]
    if replay:
        lines += [
            f"- Original X4 compiler ELF: **{replay['fixtures']} fixtures**, **{replay['complete_output_bytes_compared']:,} output bytes** plus guards, {len(replay['nodes'])} layers/controls across {len(replay['cases'])} inputs.",
            f"- Replay retires {replay['bank_counts']['xdwmac8']:,} MACs and {sum(v for k, v in replay['bank_counts'].items() if k != 'xdwmac8'):,} pair transfers, independently reconciled by mnemonic with Spike; zero unexpected traps.",
        ]
    lines += [
        "",
        "[Detailed evidence](verification.json), [consumer/LSU evidence](integration-tests.json), [authenticated summary](summary.json), [per-program counts](cases.csv).",
        "",
        "Reproduce: `gmake cvw-xdwmac8-checkpoint`. See [implementation and setup](../../../docs/cvw-xdwmac8.md).",
        "",
        "Cycle counts in cases.csv include setup, caches, console and self-checks. This checkpoint does not measure full-inference cycles, matched speedup, physical area or achievable clock frequency. Pinned sources and earlier overlays remain intact.",
        "",
    ]
    (OUTPUT / "README.md").write_text("\n".join(lines))
    print(f"Xdwmac8 CV-Wally report: PASS ({len(rows)} programs)")


if __name__ == "__main__":
    main()
