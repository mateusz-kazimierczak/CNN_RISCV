"""Checkpoint 2 fixture semantics, repeated-event validation and actual artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from investigation.common import archive_path, rewrite_command, seal, verify_archive
from investigation.diagnostics import remove_outputs, same_loaded_image, verify_analysis
from investigation.diagnostics import report as analysis_report
from investigation.replay import check_output, load_profile, report, verify_replay
from profile_spike import Elf

from compiler.build_evidence import canonical, open_build
from compiler.replay import make_fixtures


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot, cls.evidence = open_build(
            ROOT / "build/compiler/A0/rv64/build.json"
        )
        cls.oracle = Path(
            json.loads((ROOT / "build/compiler/oracle/latest.json").read_text())[
                "capture"
            ]
        )
        cls.golden = ROOT / "tests/compiler/fixtures/oracle-golden.json"
        cls.workload, cls.pack = make_fixtures(
            cls.snapshot,
            cls.evidence,
            cls.oracle,
            cls.golden,
            [4, 10, 60, 62],
            ["baseline", "zero_point"],
        )

    def bytes(self, blob):
        return self.pack[blob["offset"] : blob["offset"] + blob["bytes"]]

    def test_every_blob_hash_extent_and_alignment(self):
        self.assertEqual(
            hashlib.sha256(self.pack).hexdigest(), self.workload["fixture_pack_sha256"]
        )
        for fixture in self.workload["fixtures"]:
            for blob in [*fixture["inputs"], fixture["output"]]:
                self.assertEqual(blob["offset"] % 16, 0)
                self.assertEqual(len(self.bytes(blob)), blob["bytes"])
                self.assertEqual(
                    hashlib.sha256(self.bytes(blob)).hexdigest(), blob["sha256"]
                )

    def test_residual_restores_both_real_inputs_and_no_constant_copies(self):
        fixture = next(
            f for f in self.workload["fixtures"] if f["id"] == "baseline/node:10"
        )
        self.assertEqual([i["tensor"] for i in fixture["inputs"]], [110, 107])
        manifest = json.loads((self.oracle / "manifest.json").read_text())
        records = {t["tensor"]: t for t in manifest["cases"][0]["tensors"]}
        for blob in fixture["inputs"]:
            self.assertEqual(
                self.bytes(blob),
                (
                    self.oracle / "baseline" / records[blob["tensor"]]["file"]
                ).read_bytes(),
            )
        pointwise = self.workload["fixtures"][0]
        self.assertEqual(len(pointwise["inputs"]), 1)

    def test_readonly_view_preserves_alias_and_expected_bytes(self):
        fixture = next(
            f for f in self.workload["fixtures"] if f["id"] == "baseline/node:60"
        )
        self.assertTrue(fixture["aliases_input"])
        self.assertEqual(
            fixture["inputs"][0]["arena_offset"], fixture["output"]["arena_offset"]
        )
        self.assertEqual(
            self.bytes(fixture["inputs"][0]), self.bytes(fixture["output"])
        )

    def test_softmax_failure_is_poison_preservation_not_success_output(self):
        fixture = next(
            f for f in self.workload["fixtures"] if f["id"] == "zero_point/node:62"
        )
        self.assertEqual(fixture["expected_status"], 2)
        self.assertEqual(fixture["output_comparison"], "unchanged poison bytes")
        self.assertEqual(self.bytes(fixture["output"]), bytes([0xA7]) * 1000)
        self.assertFalse(fixture["aliases_input"])

    def test_dot_expected_accumulator_is_independent_python_integer(self):
        for fixture in self.workload["fixtures"][-2:]:
            a, w = [
                struct.unpack(f"{blob['bytes']}b", self.bytes(blob))
                for blob in fixture["inputs"]
            ]
            total = (
                sum((x + fixture["input_offset"]) * y for x, y in zip(a, w))
                + fixture["bias"]
            )
            self.assertEqual(self.bytes(fixture["output"]), struct.pack("<i", total))
        self.assertEqual(
            [f["count"] for f in self.workload["fixtures"][-2:]], [16, 320]
        )

    def test_unavailable_reference_output_and_bad_selection_rejected(self):
        for nodes, cases in [
            ([63], ["zero_point"]),
            ([4, 4], ["baseline"]),
            ([-1], ["baseline"]),
            ([4], ["unknown"]),
            ([4], ["baseline", "baseline"]),
        ]:
            with self.subTest(nodes=nodes, cases=cases), self.assertRaises(ValueError):
                make_fixtures(
                    self.snapshot, self.evidence, self.oracle, self.golden, nodes, cases
                )

    def test_oracle_identity_mismatch_fails_before_codegen(self):
        reference = json.loads((self.oracle / "manifest.json").read_text())
        reference["provenance"]["model_sha256"] = "0" * 64
        with (
            patch("compiler.replay.verify_golden", return_value=reference),
            self.assertRaisesRegex(ValueError, "mismatch"),
        ):
            make_fixtures(
                self.snapshot,
                self.evidence,
                self.oracle,
                self.golden,
                [4],
                ["baseline"],
            )


class ReplayCounterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.prefix = Path(self.temporary.name) / "profile"
        self.workload = {
            "fixtures": [
                {
                    "id": "success",
                    "kind": "kernel",
                    "node": 4,
                    "symbol": "kernel",
                    "expected_status": 0,
                    "output": {"bytes": 4},
                    "work": {"logical_macs": 1, "executed_products": 1},
                },
                {
                    "id": "known-error",
                    "kind": "kernel",
                    "node": 62,
                    "symbol": "kernel",
                    "expected_status": 2,
                    "output": {"bytes": 4},
                    "work": {},
                },
            ]
        }
        self.instructions = {
            pc: {"bits": 1, "length": 2, "mnemonic": "c.nop"}
            for pc in [128, 132, 256, 260]
        }
        for fixture in self.workload["fixtures"]:
            fixture["inputs"] = [{"sha256": "0" * 64}]
            fixture["output"]["sha256"] = "1" * 64
        self.events, self.pcs = [], []
        for i in range(2):
            for kind, name, entry, ret, total in [
                ("region", "invoke", 128, 132, 8),
                ("operator", "probe_100", 256, 260, 3),
            ]:
                eid = len(self.events)
                self.events.append(
                    {
                        "event_id": eid,
                        "kind": kind,
                        "name": name,
                        "entry": entry,
                        "return_pc": ret,
                        "total": total,
                        "complete": 1,
                        "status": i * 2,
                        "faulted": 0,
                    }
                )
                for pc, count in (
                    [(128, 5), (256, 3)] if kind == "region" else [(256, 3)]
                ):
                    self.pcs.append(
                        {
                            "event_id": eid,
                            "pc": pc,
                            "bits": 1,
                            "length": 2,
                            "count": count,
                        }
                    )

    def load(self):
        for suffix, rows in [("events", self.events), ("pcs", self.pcs)]:
            with Path(str(self.prefix) + f".{suffix}.csv").open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        return load_profile(
            self.prefix, self.workload, 128, {"kernel": 256}, self.instructions
        )

    def test_multiple_invocations_and_error_are_separate(self):
        rows = self.load()
        self.assertTrue(rows[0]["performance_result"])
        self.assertFalse(rows[1]["performance_result"])
        self.assertEqual(rows[1]["status"], 2)
        self.assertEqual(rows[0]["harness_overhead"]["value"], "5")

    def test_traps_wrong_status_incompletion_order_and_overflow_rejected(self):
        for key, value in [
            ("status", 1),
            ("faulted", 1),
            ("complete", 0),
            ("event_id", 10),
            ("entry", 260),
            ("total", 2**64),
            ("return_pc", 0),
        ]:
            old = self.events[0][key]
            self.events[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.load()
            self.events[0][key] = old
        self.events.pop()
        with self.assertRaisesRegex(ValueError, "schedule"):
            self.load()

    def test_per_pc_conservation_and_unknown_decode(self):
        self.instructions[256]["mnemonic"] = "xqmac8"
        with self.assertRaisesRegex(ValueError, "unclassified"):
            self.load()
        self.instructions[256]["mnemonic"] = "c.nop"
        self.pcs[0]["count"] = 4
        with self.assertRaisesRegex(ValueError, "reconcile"):
            self.load()

    def test_uint64_counts_preserve_exact_decimal_values(self):
        self.pcs[0]["count"] = 2**53 + 1
        self.events[0]["total"] = 2**53 + 4
        self.assertEqual(
            self.load()[0]["invocation"]["instructions"]["value"], str(2**53 + 4)
        )

    def test_stdout_requires_each_complete_comparison(self):
        rows = [
            {
                "fixture": i,
                "status": f["expected_status"],
                "guards": True,
                "bytes_compared": 4,
                "first_difference": None,
            }
            for i, f in enumerate(self.workload["fixtures"])
        ]
        text = "\n".join([*[json.dumps(r) for r in rows], "compiler replay: PASS"])
        self.assertEqual(len(check_output(text, self.workload)), 2)
        rows[1]["first_difference"] = 0
        with self.assertRaisesRegex(ValueError, "complete output"):
            check_output(
                "\n".join([*[json.dumps(r) for r in rows], "compiler replay: PASS"]),
                self.workload,
            )


class EvidenceTests(unittest.TestCase):
    def test_archive_integrity_and_safe_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "staged"
            staged.mkdir()
            (staged / "evidence.txt").write_text("frozen")
            archive = seal(staged, root / "archives", "fixture", {})
            verify_archive(archive, "fixture")
            self.assertEqual(
                archive_path(archive.parent / "latest.json"), archive.resolve()
            )
            (archive / "evidence.txt").write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                verify_archive(archive, "fixture")
            (archive.parent / "latest.json").write_text(
                canonical({"artifact_id": "../escape"})
            )
            with self.assertRaisesRegex(ValueError, "unsafe"):
                archive_path(archive.parent / "latest.json")

    def test_command_rewrite_preserves_compiler_abi_and_optimization(self):
        command = [
            "/old/cc",
            "-O2",
            "-march=rv64imc",
            "-mabi=lp64",
            "-MD",
            "-MF",
            "/old/a.d",
            "-c",
            "/old/a.cc",
            "-o",
            "/old/a.o",
        ]
        new = rewrite_command(command, "/old", Path("/frozen workspace"))
        self.assertEqual(new[0], "/old/cc")
        self.assertIn("/frozen workspace/a.cc", new)
        flags = remove_outputs(new)
        for flag in ["-O2", "-march=rv64imc", "-mabi=lp64"]:
            self.assertIn(flag, flags)
        self.assertNotIn("-MD", flags)

    def test_changed_loaded_byte_cannot_attach_gcc_evidence(self):
        binary = ROOT / "build/compiler/A0/rv64/a0.elf"
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / "altered.elf"
            data = bytearray(binary.read_bytes())
            text = Elf(binary).sections[".text"]["bytes"]
            index = data.find(text)
            self.assertGreaterEqual(index, 0)
            data[index] ^= 1
            altered.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "loaded bytes"):
                same_loaded_image(binary, altered)


class ActualInvestigationTests(unittest.TestCase):
    def replay(self, name="replay"):
        pointer = ROOT / "build/compiler" / name / "latest.json"
        if not pointer.exists():
            self.skipTest(f"{name} has not been built")
        return verify_replay(pointer)

    def test_representatives_all_build_kinds_and_exact_repeat_profiles(self):
        path, manifest, workload, rows = self.replay()
        if "rv64" not in manifest["kinds"]:
            self.skipTest("representative RV64 replay pending")
        self.assertEqual(set(manifest["kinds"]), {"native", "sanitized", "rv64"})
        self.assertEqual(workload["nodes"], [1, 4, 8, 15, 58, 61])
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r["performance_result"] for r in rows))
        self.assertNotEqual(
            json.loads((path / "rv64/build.json").read_text())["binary_sha256"],
            json.loads((path / "build_evidence/manifest.json").read_text())["build"][
                "binary_sha256"
            ],
        )

    def test_all_cases_multiinput_alias_and_softmax_diagnostic(self):
        _, manifest, workload, _ = self.replay("replay-correctness")
        self.assertEqual(set(manifest["kinds"]), {"native", "sanitized"})
        self.assertEqual(len(workload["cases"]), 8)
        self.assertEqual(len(workload["fixtures"]), 74)
        self.assertEqual(
            sum(f["expected_status"] == 2 for f in workload["fixtures"]), 1
        )

    def test_rv64_repeats_preserve_softmax_error_as_diagnostic(self):
        _, manifest, _, rows = self.replay("replay-edge")
        self.assertEqual(manifest["kinds"], ["rv64"])
        failed = [r for r in rows if not r["performance_result"]]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["fixture"], "zero_point/node:62")
        self.assertEqual(failed[0]["status"], 2)
        self.assertEqual(failed[0]["byte_comparison"], "unchanged poison bytes")

    def test_actual_corruption_detection_native_and_sanitized(self):
        path, manifest, _, _ = self.replay("replay-correctness")
        for kind in manifest["kinds"]:
            binary = path / kind / "replay"
            result = subprocess.run(
                [binary, "--corrupt-guard"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("guard failure before invoke", result.stdout)
            result = subprocess.run(
                [binary, "--corrupt-output"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(
                json.loads(result.stdout.splitlines()[0])["first_difference"], 0
            )

    def test_saved_replay_report_with_no_live_project_tree(self):
        path, _, _, _ = self.replay()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("investigation.replay.ROOT", Path(directory) / "absent"),
        ):
            summary = report(path, Path(directory) / "report")
            self.assertEqual(summary["fixtures_verified_per_build"], 8)

    def test_gcc_diagnostics_bound_to_measured_loaded_image(self):
        pointer = ROOT / "build/compiler/gcc-analysis/latest.json"
        if not pointer.exists():
            self.skipTest("GCC investigation pending")
        _, data = verify_analysis(pointer)
        self.assertEqual(len(data["units"]), 5)
        self.assertTrue(data["loadable_identical"])
        model = next(u for u in data["units"] if u["source"].endswith("model.cc"))
        for stage in ["Optimized GIMPLE", "Final RTL", "Emitted assembly"]:
            artifact = next(a for a in model["artifacts"] if a["stage"] == stage)
            self.assertTrue(
                any(f["linkageName"] == "a0_node_04" for f in artifact["functions"])
            )

    def test_saved_gcc_report_needs_no_live_project_or_compiler(self):
        pointer = ROOT / "build/compiler/gcc-analysis/latest.json"
        if not pointer.exists():
            self.skipTest("GCC investigation pending")
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("investigation.diagnostics.ROOT", Path(directory) / "absent"),
            patch(
                "investigation.diagnostics.run",
                side_effect=AssertionError("report must not run GCC"),
            ),
        ):
            data = analysis_report(pointer, Path(directory) / "report")
            self.assertTrue(data["loadable_identical"])
            self.assertEqual(
                json.loads((Path(directory) / "report/summary.json").read_text())[
                    "measured_elf_sha256"
                ],
                data["measured_elf_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
