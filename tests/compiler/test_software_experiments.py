"""Guard the reordered experimental controls and accepted final selection."""

import contextlib
import io
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from compiler.cli import main
from tools import run_software_experiments as runner
from tools.report_software_experiments import chart, comparison, validate_parent
from tools.run_software_experiments import MANIFEST, stages


class SoftwareSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.plans = []
        for i, stage in enumerate(stages()):
            output = Path(cls.temp.name) / str(i)
            with contextlib.redirect_stdout(io.StringIO()):
                status = main(
                    [
                        "generate",
                        str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                        "--config",
                        stage["config"],
                        "--output-dir",
                        str(output),
                        *stage["flags"],
                    ]
                )
            if status:
                raise AssertionError(f"stage generation failed: {stage['id']}")
            cls.plans.append(json.loads((output / "kernel_plan.json").read_text()))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def changed_nodes(self, before, after):
        return [
            new["node"]
            for old, new in zip(self.plans[before]["nodes"], self.plans[after]["nodes"])
            if old != new
        ]

    def test_submission_labels_keep_frozen_baseline_and_compiler_distinct(self):
        spec = json.loads(MANIFEST.read_text())
        self.assertEqual(spec["baseline"]["id"], "A0")
        self.assertEqual(spec["baseline"]["checkpoint"], "B0")
        selected = stages()
        self.assertEqual([s["id"] for s in selected], [f"B1.{i}" for i in range(1, 8)])
        self.assertEqual(selected[0]["config"], "A0")
        self.assertEqual(selected[0]["checkpoint"], "A0-reordered")
        self.assertEqual(selected[-1]["checkpoint"], "B1-reordered-06-spatial")

    def test_each_convolution_control_has_only_its_intended_scope(self):
        self.assertEqual(len(self.changed_nodes(0, 1)), 32)
        self.assertEqual(len(self.changed_nodes(1, 2)), 16)
        self.assertTrue(
            all(
                self.plans[2]["nodes"][n]["kind"] == "DEPTHWISE_CONV_2D"
                for n in self.changed_nodes(1, 2)
            )
        )
        self.assertEqual(self.changed_nodes(2, 3), [1])
        self.assertEqual(len(self.changed_nodes(5, 6)), 32)
        self.assertTrue(
            all(
                self.plans[6]["nodes"][n]["implementation"]
                == "rv64imc/pointwise_dot8_spatial2_oc2/int8"
                for n in self.changed_nodes(5, 6)
            )
        )

    def test_final_plan_equals_preserved_accepted_selection(self):
        selection = json.loads(
            (ROOT / "results/profiling/B1-software/selection.json").read_text()
        )
        import hashlib

        from compiler.build_evidence import canonical

        self.assertEqual(
            hashlib.sha256(canonical(self.plans[-1]).encode()).hexdigest(),
            selection["selection_evidence"]["kernel_plan_sha256"],
        )
        self.assertEqual(
            json.loads(MANIFEST.read_text())["inline_nodes"],
            selection["selection_evidence"]["inline_requantization_nodes"],
        )
        for plan in self.plans[1:-1]:
            self.assertFalse(
                any(
                    "oc4" in n["implementation"] or "spatial2" in n["implementation"]
                    for n in plan["nodes"]
                )
            )

    def test_chart_groups_stem_but_adjacent_deltas_telescope(self):
        values = [100, 90, 80, 70, 60, 50, 40, 30]
        rows = [
            {
                "stage": "A0",
                "title": "Baseline",
                "present": True,
                "instructions": values[0],
            }
        ]
        rows += [
            {
                "stage": s["id"],
                "title": s["title"],
                "present": s["present"],
                "instructions": n,
            }
            for s, n in zip(stages(), values[1:])
        ]
        svg = chart(rows)
        self.assertNotIn("B1.4  Stem", svg)
        self.assertIn("B1.5  Compiler/runtime cleanup", svg)
        self.assertEqual(sum(row["present"] for row in rows), 7)
        self.assertEqual(
            sum(
                comparison(a, b)["instructions_removed"]
                for a, b in itertools.pairwise(values)
            ),
            70,
        )


class LineageTests(unittest.TestCase):
    def test_changed_parent_summary_or_manifest_is_rejected(self):
        from compiler.build_evidence import canonical, digest

        with tempfile.TemporaryDirectory() as temp:
            child, parent = Path(temp) / "child", Path(temp) / "parent"
            child.mkdir()
            parent.mkdir()
            summary = {"checkpoint": "B1.3", "capture_id": "new-parent"}
            (parent / "manifest.json").write_text(canonical({"identity": "new-parent"}))
            (child / "parent-summary.json").write_text(canonical(summary))
            (child / "parent-identity.txt").write_text(
                digest(parent / "manifest.json") + "\n"
            )
            validate_parent(child, parent, summary)
            with self.assertRaisesRegex(ValueError, "previous stage"):
                validate_parent(
                    child, parent, {**summary, "capture_id": "historical-parent"}
                )
            (parent / "manifest.json").write_text(canonical({"identity": "changed"}))
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                validate_parent(child, parent, summary)


class CorrectnessReceiptTests(unittest.TestCase):
    def test_stale_binary_incomplete_coverage_and_changed_output_are_rejected(self):
        from compiler.build_evidence import canonical, digest

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated = root / "generated"
            golden_path = root / "tests/compiler/fixtures/oracle-golden.json"
            golden_path.parent.mkdir(parents=True)
            reports = []
            for kind in ("native", "capture", "sanitized"):
                case_dir = generated / kind / "captures/baseline"
                case_dir.mkdir(parents=True)
                (case_dir / "output.bin").write_bytes(b"exact output")
                sha = digest(case_dir / "output.bin")
                report = {
                    "status": "PASS",
                    "configuration": "B1",
                    "kind": kind,
                    "binary_sha256": "expected-elf",
                    "cases": [
                        {
                            "name": "baseline",
                            "status": 0,
                            "nodes_compared": 0 if kind == "native" else 64,
                            "files": {"output.bin": sha},
                        }
                    ],
                }
                path = generated / kind / "differential.json"
                path.write_text(canonical(report))
                reports.append((path, report))
            golden_path.write_text(
                canonical(
                    {
                        "cases": [
                            {
                                "name": "baseline",
                                "expected_signal": None,
                                "expected_nodes": 64,
                                "output_sha256": sha,
                            }
                        ]
                    }
                )
            )
            with (
                patch.object(runner, "ROOT", root),
                patch.object(
                    runner,
                    "verify_build",
                    return_value={
                        "binary_sha256": "expected-elf",
                        "configuration": "B1",
                    },
                ),
            ):
                self.assertEqual(len(runner.verify_correctness(generated)["builds"]), 3)
                path, report = reports[0]
                path.write_text(canonical({**report, "binary_sha256": "stale-elf"}))
                with self.assertRaisesRegex(ValueError, "stale differential"):
                    runner.verify_correctness(generated)
                path.write_text(canonical({**report, "cases": []}))
                with self.assertRaisesRegex(ValueError, "incomplete differential"):
                    runner.verify_correctness(generated)
                path.write_text(canonical(report))
                (generated / "native/captures/baseline/output.bin").write_bytes(
                    b"changed"
                )
                with self.assertRaisesRegex(ValueError, "output changed"):
                    runner.verify_correctness(generated)


if __name__ == "__main__":
    unittest.main()
