"""Revalidate archived full-inference RTL evidence without remote execution."""

import base64

from compiler.build_evidence import digest
from tools.cvw.collect_custom import validate_pass
from tools.hardware_experiments import ROOT, custom_counts, read, require


def validate_rtl(stage, bundle):
    paths = stage["rtl"]
    summary_path, snapshot_path, contract_path = [
        ROOT / paths[k] for k in ("summary", "snapshot", "contract")
    ]
    summary, snapshot, contract = map(
        read, (summary_path, snapshot_path, contract_path)
    )
    label = stage["presentation"]
    data = summary["runs"][label]
    captured = snapshot["runs"][label]
    record = captured["record"]
    selected = bundle["summary"]
    require(
        data["status"] == record["status"] == "PASS", "RTL inference is not complete"
    )
    require(
        data["elf_sha256"] == record["elf_sha256"] == selected["elf_sha256"],
        "RTL/Spike executable mismatch",
    )
    require(
        data["integration"] == record["integration"],
        "RTL integration changed after collection",
    )
    require(
        record["elf_sha256"] == contract[label]["elf_sha256"],
        "RTL workload contract mismatch",
    )
    require(
        int(record["metrics"]["instructions"])
        == int(selected["inference"]["instructions"]["value"]),
        "RTL/Spike instruction mismatch",
    )
    require(
        int(data["cycles"]) == int(record["metrics"]["cycles"]) > 0,
        "RTL cycle count mismatch",
    )
    require(
        int(data["instructions"]) == int(record["metrics"]["instructions"]),
        "RTL summary instruction mismatch",
    )
    require(
        record["output_bytes_compared"] == 1000
        and record["output_sha256"] == contract["expected_output_sha256"],
        "RTL full-output proof incomplete",
    )
    if label == "B1":
        require(
            record["simulator_sha256"]
            == snapshot["simulator_sha256"]
            == summary["simulator_sha256"],
            "baseline simulator mismatch",
        )
        require(snapshot["smoke"] == summary["smoke"], "baseline smoke proof changed")
        require(
            set(snapshot["smoke"]["cases"]) == {"correct", "wrong-count", "incomplete"}
            and all(c["status"] == "PASS" for c in snapshot["smoke"]["cases"].values()),
            "baseline monitor gates incomplete",
        )
        simulator = record["simulator_sha256"]
        output_policy = "archived PASS record and pinned output SHA-256; raw output bytes absent from baseline snapshot"
    else:
        require(
            record["contract_sha256"] == digest(contract_path),
            "RTL contract identity changed",
        )
        output = base64.b64decode(captured["output_base64"], validate=True)
        validate_pass(
            record, contract[label], contract["expected_output_sha256"], output
        )
        require(
            record["simulator_sha256"]
            == captured["live_simulator_sha256"]
            == data["simulator_sha256"],
            "archived RTL simulator identity mismatch",
        )
        smoke = captured["smoke"]
        require(smoke == data["smoke"], "RTL smoke proof changed")
        required = {"correct", "wrong-count", "wrong-custom", "incomplete"}
        if label in ("X3", "X4", "X5"):
            required.add("wrong-postinc")
        if label in ("X4", "X5"):
            required.add("wrong-bank")
        require(
            set(smoke["cases"]) == required
            and all(v["status"] == "PASS" for v in smoke["cases"].values()),
            "RTL monitor gates incomplete",
        )
        actual = custom_counts(selected)
        for opcode, count in contract[label]["custom_instructions"].items():
            require(
                actual.get(opcode, 0) == int(count),
                f"custom opcode/RTL contract mismatch: {opcode}",
            )
        require(
            sum(map(int, contract[label]["custom_instructions"].values()))
            == sum(actual.values()),
            "custom contract omits an opcode",
        )
        simulator = record["simulator_sha256"]
        if label == "X5":
            require(
                record["expected_simulator_sha256"]
                == simulator
                == smoke["hardware_reuse"]["simulator_sha256"],
                "X5 did not reuse the X4 hardware simulator",
            )
        output_policy = (
            "all 1000 output bytes decoded and rehashed from archived snapshot"
        )
    require(
        record["integration"]["wally_revision"]
        == "712ee9719467e9e9987cebd55926ae8e01b08770",
        "RTL core revision differs",
    )
    instructions, cycles = int(data["instructions"]), int(data["cycles"])
    return {
        "stage": label,
        "instructions": instructions,
        "cycles": cycles,
        "cpi": cycles / instructions,
        "elf_sha256": record["elf_sha256"],
        "simulator_sha256": simulator,
        "configuration_sha256": data["integration"]["config_sha256"],
        "summary_sha256": digest(summary_path),
        "snapshot_sha256": digest(snapshot_path),
        "contract_sha256": digest(contract_path),
        "output_validation": output_policy,
        "source_summary": paths["summary"],
        "source_snapshot": paths["snapshot"],
        "physical_fmax": None,
        "area": None,
    }


def validate_hardware_reuse(x4, x5):
    require(x4["simulator_sha256"] == x5["simulator_sha256"], "X4/X5 simulator differs")
    require(
        x4["configuration_sha256"] == x5["configuration_sha256"],
        "X4/X5 RTL configuration differs",
    )
