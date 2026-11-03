"""Midterm evidence must remain verified without requiring RTL artifacts."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from tools.report_midterm import FROZEN_BASELINE, compiler_row, load_baseline


class MidtermEvidenceTests(unittest.TestCase):
    def test_frozen_baseline_is_the_litert_reference(self):
        baseline, identity = load_baseline(FROZEN_BASELINE)
        self.assertEqual(baseline["inference"]["instructions"], 4_867_278_370)
        self.assertEqual(identity["kind"], "retained_frozen_reference")

    def test_fresh_baseline_requires_its_raw_capture(self):
        baseline = json.loads(FROZEN_BASELINE.read_text())
        baseline["configuration"] = "midterm-unit-test-missing-raw"
        (ROOT / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as temp:
            path = Path(temp) / "summary.json"
            path.write_text(json.dumps(baseline))
            with self.assertRaises(FileNotFoundError):
                load_baseline(path)

    def test_incomplete_custom_capture_is_rejected(self):
        bundle = {"summary": {"gates": {"full_output_bytes_compared": 999}}}
        with self.assertRaisesRegex(ValueError, "incomplete full-model"):
            compiler_row("X1", "Packed MAC", bundle)

    def test_postincrement_counts_are_not_added_twice_to_instruction_mix(self):
        summary = json.loads((ROOT / "results/profiling/X3-selected/summary.json").read_text())
        row = compiler_row("X3", "Post-increment", {"summary": summary})
        postinc = sum(int(v["value"]) for v in summary["inference"]["postincrement"].values())
        self.assertGreater(postinc, 0)
        self.assertEqual(row["custom_encoding_instructions"], row["custom"] + postinc)
        self.assertEqual(row["memory_instructions"], row["load"] + row["store"])
        changed = copy.deepcopy(summary)
        changed["units"][0].setdefault("expected_xpostinc_instructions", {})["load"] = 1
        with self.assertRaisesRegex(ValueError, "custom utilization"):
            compiler_row("X3", "Post-increment", {"summary": changed})


if __name__ == "__main__":
    unittest.main()
