"""Observability foundation: boundaries, provenance, and exact cost partitions."""

from __future__ import annotations

import copy
import csv
import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from compiler.build_evidence import (
    canonical,
    digest,
    local_file,
    open_build,
    snapshot_build,
    verify_snapshot,
)
from compiler.execution_plan import (
    ExecutionPlan,
    make_execution_plan,
    validate_execution_plan,
)
from compiler.frontend import import_model
from compiler.ir import ModelError
from compiler.lowering import lower_graph
from tools.profile_compiler import (
    capture_directory,
    check_output,
    compare_summary,
    event_metrics,
    load_capture,
    make_summary,
    resolve_boundaries,
    uint,
    verify_capture,
)


class ExecutionPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = lower_graph(
            import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        )
        cls.plan = make_execution_plan(
            cls.model,
            json.loads((ROOT / "build/compiler/A0/source_map.json").read_text()),
        )

    def test_actual_plan_roundtrip_and_work(self):
        self.assertEqual(ExecutionPlan.from_json(self.plan.to_json()), self.plan)
        self.assertEqual(
            sum(u.work["logical_macs"] for u in self.plan.units), 385187552
        )
        self.assertEqual(
            sum(u.work["executed_products"] for u in self.plan.units), 381239488
        )
        self.assertIn("preflight", self.plan.units[62].notes[0])
        self.assertTrue(self.plan.units[60].memory["tensors"])

    def test_split_shared_and_eliminated_origins_are_explicit(self):
        # Two units implement one origin; a third unit represents two origins.
        units = [
            replace(self.plan.units[0], id="split-a"),
            replace(self.plan.units[0], id="split-b", order=1),
            replace(self.plan.units[1], nodes=(1, 2), order=2),
        ]
        origins = [
            {
                "node": n.index,
                "unit_ids": [u.id for u in units if n.index in u.nodes],
                "disposition": "executed" if n.index <= 2 else "eliminated",
                "reason": "fixture proves no runtime operation",
            }
            for n in self.model.graph.nodes
        ]
        plan = replace(self.plan, units=tuple(units), origins=tuple(origins))
        validate_execution_plan(plan, self.model.graph)
        origins[0]["unit_ids"] = ["split-a"]
        with self.assertRaisesRegex(ModelError, "relationships"):
            validate_execution_plan(plan, self.model.graph)

    def test_bad_schedule_graph_operands_and_source_rejected(self):
        for plan in [
            replace(self.plan, graph_ir_sha256="bad"),
            replace(self.plan, units=(self.plan.units[0], self.plan.units[0])),
            replace(
                self.plan,
                units=(replace(self.plan.units[0], inputs=(-1,)), *self.plan.units[1:]),
            ),
            replace(
                self.plan,
                units=(replace(self.plan.units[0], source={}), *self.plan.units[1:]),
            ),
        ]:
            with self.subTest(plan=plan.units[0].source), self.assertRaises(ModelError):
                validate_execution_plan(plan, self.model.graph)

    def test_symbols_resolved_by_elf_not_label_or_guessed_address(self):
        syms = [{"name": self.plan.inference_symbol, "address": 128}] + [
            {"name": u.symbol, "address": 256 + 4 * i}
            for i, u in enumerate(self.plan.units)
        ]
        ins = {s["address"]: {} for s in syms}

        class FakeElf:
            def __init__(self, path):
                self.sections = {".text": {"address": 128, "size": 1024}}

        with (
            patch("tools.profile_compiler.symbols", return_value=syms),
            patch("tools.profile_compiler.disassemble", return_value=ins),
            patch("tools.profile_compiler.Elf", FakeElf),
        ):
            boundaries, text, _, _ = resolve_boundaries(Path("ignored"), self.plan)
            self.assertEqual(len(boundaries["units"]), 64)
            self.assertNotIn("allocate", text)
            syms.append({"name": self.plan.units[0].symbol, "address": 900})
            with self.assertRaisesRegex(ValueError, "expected one ELF entry"):
                resolve_boundaries(Path("ignored"), self.plan)


class CaptureValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prefix = Path(self.temp.name) / "capture"
        self.boundaries = {
            "root": 128,
            "units": [{"unit_id": "node:0", "entry": 256, "probe": "probe_100"}],
        }
        self.instructions = {
            p: {"bits": 1, "length": 2, "mnemonic": "c.nop"}
            for p in (128, 132, 256, 260)
        }
        self.events = [
            {
                "event_id": 0,
                "kind": "region",
                "name": "invoke",
                "entry": 128,
                "return_pc": 132,
                "complete": 1,
                "status": 0,
                "total": 8,
                "faulted": 0,
            },
            {
                "event_id": 1,
                "kind": "operator",
                "name": "probe_100",
                "entry": 256,
                "return_pc": 260,
                "complete": 1,
                "status": 0,
                "total": 3,
                "faulted": 0,
            },
        ]
        self.pcs = [
            {"event_id": 0, "pc": 128, "bits": 1, "length": 2, "count": 5},
            {"event_id": 0, "pc": 256, "bits": 1, "length": 2, "count": 3},
            {"event_id": 1, "pc": 256, "bits": 1, "length": 2, "count": 3},
        ]

    def load(self):
        for suffix, rows in (("events", self.events), ("pcs", self.pcs)):
            with Path(str(self.prefix) + f".{suffix}.csv").open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        return load_capture(self.prefix, self.boundaries, self.instructions)

    def test_no_allocation_required_and_exact_partition(self):
        root, units, residual = self.load()
        self.assertEqual(root["total"], 8)
        self.assertEqual(units[0]["total"], 3)
        self.assertEqual(residual, {128: 5})

    def test_bad_event_identity_completion_trap_return_and_status(self):
        for field, value in [
            ("name", "other"),
            ("kind", "region"),
            ("entry", 128),
            ("return_pc", 0),
            ("event_id", 2),
            ("complete", 0),
            ("faulted", 1),
            ("status", 2),
            ("total", 0),
        ]:
            old = self.events[1][field]
            self.events[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load()
            self.events[1][field] = old

    def test_missing_or_extra_event(self):
        self.events.append(dict(self.events[-1]))
        with self.assertRaisesRegex(ValueError, "coverage"):
            self.load()
        self.events = self.events[:1]
        with self.assertRaisesRegex(ValueError, "coverage"):
            self.load()

    def test_duplicate_bits_unknown_instruction_and_overflow_rejected(self):
        original = copy.deepcopy(self.pcs)
        for key, value in [
            ("bits", 2),
            ("length", 4),
            ("event_id", 2),
            ("count", 0),
            ("count", 2**64),
            ("count", -1),
        ]:
            self.pcs = copy.deepcopy(original)
            self.pcs[2][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.load()
        self.pcs = original + [original[-1]]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.load()
        self.pcs = original
        self.instructions[256]["mnemonic"] = "unknown_custom"
        with self.assertRaisesRegex(ValueError, "unclassified"):
            self.load()

    def test_per_pc_partition_rejects_compensating_totals(self):
        self.pcs[2]["pc"] = 128
        self.pcs[2]["count"] = 6
        self.events[1]["entry"] = 128
        self.boundaries["units"][0]["entry"] = 128
        self.events[1]["total"] = 6
        with self.assertRaisesRegex(ValueError, "exceed"):
            self.load()

    def test_counts_above_javascript_precision_remain_exact(self):
        big = 2**53 + 17
        self.pcs[0]["count"] = big
        self.events[0]["total"] = big + 3
        root, _, _ = self.load()
        m = event_metrics(root, "fixture", {"logical_macs": 7})
        self.assertEqual(m["instructions"]["value"], str(big + 3))
        self.assertEqual(
            m["logical_macs_per_instruction"]["value"]["denominator"], str(big + 3)
        )
        self.assertEqual(m["executed_products"]["evidence"], "unavailable")
        for value in (True, "1.0", "-1", 2**64):
            with self.assertRaises(ValueError):
                uint(value)

    def test_full_output_comparison_not_only_checksum(self):
        output = (ROOT / "tests/compiler/fixtures/baseline-output.bin").read_bytes()
        text = (
            "A0 EfficientNet-Lite0 inference: PASS\noutput_top_index=21 output_top_score=48 output_sum=215\noutput_fnv1a=0x4b6a91e2\noutput_hex="
            + output.hex()
        )
        check_output(text, output)
        with self.assertRaisesRegex(ValueError, "1,000-byte"):
            check_output(text[:-2] + "ff", output)

    def test_comparison_matches_nodes_not_pc_or_unit_names(self):
        unit = {
            "id": "renamed",
            "nodes": [4],
            "metrics": {"instructions": {"value": "90"}},
        }
        comparison = compare_summary("old", 150, {"4": 100}, 140, [unit])
        self.assertEqual(comparison["nodes"][0]["delta"], "-10")
        split = {
            **unit,
            "id": "second-part",
            "metrics": {"instructions": {"value": "5"}},
        }
        self.assertEqual(
            compare_summary("old", 150, {"4": 100}, 140, [unit, split])["nodes"][0][
                "after"
            ],
            "95",
        )
        unit["nodes"] = [4, 5]
        self.assertEqual(
            compare_summary("old", 150, {"4": 100}, 140, [unit])["nodes"], []
        )
        self.assertEqual(
            compare_summary("old", 150, {"4": 100}, 140, [unit, split])["nodes"], []
        )

    def test_capture_pointer_cannot_escape_storage(self):
        pointer = Path(self.temp.name) / "latest.json"
        pointer.write_text(json.dumps({"capture_id": "../escape"}))
        with self.assertRaisesRegex(ValueError, "pointer"):
            capture_directory(pointer)


class BuildSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.generated = self.root / "generated"
        self.output = self.generated / "rv64"
        self.output.mkdir(parents=True)
        (self.root / "tools").mkdir()
        (self.root / "tools/build_a0.py").write_text("fake builder")
        (self.root / "source.cc").write_text("source at build time")
        (self.generated / "plan.json").write_text("plan")
        (self.generated / "manifest.json").write_text(
            canonical(
                {
                    "source_sha256": {"source.cc": digest(self.root / "source.cc")},
                    "artifacts": {"plan.json": digest(self.generated / "plan.json")},
                }
            )
        )
        (self.output / "a0.elf").write_bytes(b"fixture binary")
        self.record = {
            "kind": "rv64",
            "binary": "generated/rv64/a0.elf",
            "binary_sha256": digest(self.output / "a0.elf"),
            "driver_sha256": digest(self.root / "tools/build_a0.py"),
            "source_sha256": {"source.cc": digest(self.root / "source.cc")},
            "dependency_sha256": {"source.cc": digest(self.root / "source.cc")},
            "generation_manifest_sha256": digest(self.generated / "manifest.json"),
        }

    def snapshot(self):
        reference = snapshot_build(
            self.output,
            self.generated,
            self.record,
            self.root,
            self.record["source_sha256"],
        )
        (self.output / "build.json").write_text(
            canonical({**self.record, "evidence": reference})
        )
        return open_build(self.output / "build.json")

    def test_offline_after_sources_and_generated_files_change(self):
        path, expected = self.snapshot()
        (self.root / "source.cc").write_text("later source")
        (self.generated / "plan.json").unlink()
        (self.output / "a0.elf").unlink()
        self.assertEqual(open_build(self.output / "build.json")[1], expected)
        self.assertEqual(
            verify_snapshot(path)["source_snapshot_status"], "verified build-time bytes"
        )

    def test_build_record_and_snapshot_tampering_rejected(self):
        path, data = self.snapshot()
        build = json.loads((self.output / "build.json").read_text())
        build["binary_sha256"] = "forged"
        (self.output / "build.json").write_text(canonical(build))
        with self.assertRaisesRegex(ValueError, "disagrees"):
            open_build(self.output / "build.json")
        blob = path.parent / data["files"]["source.cc"]["blob"]
        blob.write_text("tampered")
        with self.assertRaisesRegex(ValueError, "changed"):
            verify_snapshot(path)

    def test_stale_source_and_unsafe_path_rejected(self):
        (self.root / "source.cc").write_text("changed during compilation")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.snapshot()
        for name in ("../escape", "/absolute"):
            with self.assertRaisesRegex(ValueError, "unsafe"):
                local_file(self.root, name)

    def test_disagreement_with_compile_time_dependency_rejected(self):
        self.record["dependency_sha256"]["source.cc"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.snapshot()


class ActualProfileTests(unittest.TestCase):
    def actual_capture(self):
        pointer = ROOT / "build/profiling/compiler/latest.json"
        if not pointer.exists():
            self.skipTest("full A0 capture not yet collected")
        return capture_directory(pointer)

    def test_actual_profile_when_collected(self):
        capture = self.actual_capture()
        data = verify_capture(capture)
        self.assertEqual(len(data[-2]), 64)
        self.assertEqual(
            data[6]["total"], sum(e["total"] for e in data[-2]) + sum(data[-1].values())
        )

    def test_relocated_report_needs_no_live_sources_model_or_simulator(self):
        capture = self.actual_capture()
        with tempfile.TemporaryDirectory() as directory:
            relocated = Path(directory) / capture.name
            shutil.copytree(capture, relocated)
            with patch(
                "tools.profile_compiler.ROOT", Path(directory) / "absent-working-tree"
            ):
                summary = make_summary(relocated)
            self.assertEqual(summary["capture_id"], capture.name)
            self.assertEqual(summary["gates"]["full_output_bytes_compared"], 1000)
            self.assertIsNone(summary["allocation"])
            (relocated / "run1.pcs.csv").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "changed"):
                verify_capture(relocated)


if __name__ == "__main__":
    unittest.main()
