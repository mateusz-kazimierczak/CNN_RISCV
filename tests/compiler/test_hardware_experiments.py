"""Submission configuration and evidence rejection tests for the ISA sequence."""

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from tools import hardware_rtl_evidence as rtl_evidence
from tools.hardware_experiments import (
    RESULTS,
    flags,
    load_capture,
    read,
    stages,
    validate_selection,
    validate_transition,
)


class HardwareProgressionTests(unittest.TestCase):
    def test_ablation_and_alternative_edges_are_distinct(self):
        selected = {s["id"]: s for s in stages()}
        self.assertEqual(selected["X4"]["parent"], "D1")
        self.assertEqual(selected["D1"]["config"], "X3")
        self.assertEqual(selected["X3"]["parent"], selected["X3.broad"]["parent"])
        self.assertNotIn("presentation", selected["D1"])
        self.assertNotIn("rtl", selected["D1"])
        self.assertEqual(selected["X5"]["options"], selected["X4"]["options"])
        self.assertEqual(selected["X5"]["kind"], "software_on_existing_isa")

    def test_cumulative_options_do_not_emit_conflicting_overrides(self):
        for stage in stages():
            command = flags(stage)
            switches = [v for v in command if v.startswith("--")]
            self.assertEqual(len(switches), len(set(switches)))
        selected = {s["id"]: s for s in stages()}
        self.assertEqual(selected["X1.1"]["options"]["pointwise_block"], 2)
        self.assertEqual(selected["X1.4"]["options"]["pointwise_block"], 4)
        self.assertEqual(selected["X2.2"]["options"]["xrequant_add_register_bits"], 32)
        self.assertEqual(selected["X2.3"]["options"]["xrequant_add_register_bits"], 64)

    def test_changed_pointwise_plan_cannot_be_relabelled_as_accepted_B1(self):
        stage = stages()[0]
        bundle = load_capture(RESULTS / stage["source"] / "summary.json")
        validate_selection(stage, bundle)
        changed = copy.deepcopy(stage)
        changed["options"]["pointwise_block"] = 4
        with self.assertRaisesRegex(ValueError, "explicit selection"):
            validate_selection(changed, bundle)

    def test_depthwise_control_rejects_change_to_unrelated_operator(self):
        units = [
            {
                "nodes": [n],
                "implementation": "depthwise" if n < 16 else "pointwise",
                "metrics": {"instructions": {"value": "100"}},
            }
            for n in range(64)
        ]
        before = {
            "summary": {
                "model_sha256": "model",
                "input": {"seed": 1},
                "boundary_policy": "same",
                "units": units,
            }
        }
        after = copy.deepcopy(before)
        for unit in after["summary"]["units"][:16]:
            unit["metrics"]["instructions"]["value"] = "90"
        self.assertEqual(len(validate_transition({"id": "D1"}, before, after)), 16)
        after["summary"]["units"][20]["metrics"]["instructions"]["value"] = "90"
        with self.assertRaisesRegex(ValueError, "ablation scope"):
            validate_transition({"id": "D1"}, before, after)


class ArchivedRTLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stage = next(s for s in stages() if s["id"] == "X3")
        cls.bundle = load_capture(RESULTS / cls.stage["source"] / "summary.json")
        cls.inputs = [
            read(ROOT / cls.stage["rtl"][k])
            for k in ("summary", "snapshot", "contract")
        ]

    def test_cycle_summary_cannot_override_completed_run(self):
        data = copy.deepcopy(self.inputs)
        data[0]["runs"]["X3"]["cycles"] = str(int(data[0]["runs"]["X3"]["cycles"]) + 1)
        with (
            patch.object(rtl_evidence, "read", side_effect=data),
            self.assertRaisesRegex(ValueError, "cycle count mismatch"),
        ):
            rtl_evidence.validate_rtl(self.stage, self.bundle)

    def test_truncated_archived_output_is_rejected(self):
        import base64

        data = copy.deepcopy(self.inputs)
        data[1]["runs"]["X3"]["output_base64"] = base64.b64encode(bytes(999)).decode()
        with (
            patch.object(rtl_evidence, "read", side_effect=data),
            self.assertRaisesRegex(ValueError, "incorrect full output"),
        ):
            rtl_evidence.validate_rtl(self.stage, self.bundle)

    def test_X5_requires_identical_simulator_and_configuration(self):
        a = {"simulator_sha256": "same", "configuration_sha256": "same-config"}
        rtl_evidence.validate_hardware_reuse(a, a)
        with self.assertRaisesRegex(ValueError, "simulator differs"):
            rtl_evidence.validate_hardware_reuse(
                a, {**a, "simulator_sha256": "changed"}
            )
        with self.assertRaisesRegex(ValueError, "configuration differs"):
            rtl_evidence.validate_hardware_reuse(
                a, {**a, "configuration_sha256": "changed"}
            )


if __name__ == "__main__":
    unittest.main()
