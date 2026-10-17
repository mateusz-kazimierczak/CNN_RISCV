"""Compiler viewer export gates, including independence from live source bytes."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from explorer.compiler_bundle import attach_analysis, compiler_context
from export_explorer import export_bundle, read_sources
from profile_spike import ROOT

CAPTURE = ROOT / "build/profiling/compiler/latest.json"
ANALYSIS = ROOT / "build/compiler/gcc-analysis/latest.json"


class FrozenSourceMappingTests(unittest.TestCase):
    def test_original_prefix_and_upstream_paths_do_not_need_live_files(self):
        frozen = {
            "build/compiler/A0/model.cc",
            ".deps/tflite-micro/tensorflow/lite/example.h",
        }
        dwarf = "0x80\na0_node_04\n/old/checkout/build/compiler/A0/model.cc:25\ninline_helper\ntensorflow/lite/example.h:9\n"
        with (
            patch("export_explorer.capture", return_value=dwarf),
            patch.object(
                Path, "exists", side_effect=AssertionError("live filesystem lookup")
            ),
        ):
            frames = read_sources(
                Path("saved.elf"), ["128"], frozen, Path("/old/checkout")
            )["128"]
        self.assertEqual(
            [f["file"] for f in frames],
            [
                "build/compiler/A0/model.cc",
                ".deps/tflite-micro/tensorflow/lite/example.h",
            ],
        )


@unittest.skipUnless(CAPTURE.exists(), "verified local A0 capture required")
class CompilerBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = compiler_context(CAPTURE)

    def test_metadata_preserves_units_origins_work_and_views(self):
        c = self.context
        self.assertEqual(c["invoke"]["total"], 6063975187)
        self.assertEqual(c["overhead"], 85)
        self.assertEqual(len(c["executionPlan"]["units"]), 64)
        self.assertEqual(c["graph"]["nodes"][4]["unitIds"], ["node:4"])
        self.assertEqual(c["graph"]["nodes"][4]["executed_products"], "19267584")
        self.assertEqual(c["memoryPlan"]["arena_bytes"], 1505280)
        self.assertTrue(
            next(a for a in c["memoryPlan"]["aliases"] if a["node"] == 60)["enabled"]
        )
        self.assertNotIn("buffers", c["graph"])
        self.assertEqual(
            c["summary"]["inference"]["instructions"]["evidence"], "measured"
        )
        self.assertEqual(c["executionPlan"]["units"][4]["work"]["evidence"], "derived")

    def test_export_uses_saved_sources_and_omits_weights(self):
        read_bytes = Path.read_bytes
        live_sources = {
            (ROOT / key).resolve()
            for key in self.context["evidence"]["files"]
            if key.endswith((".h", ".cc", ".S", ".cpp"))
        }

        def frozen_only(path):
            if path.resolve() in live_sources:
                raise AssertionError(
                    "export attempted to read live source: " + str(path)
                )
            return read_bytes(path)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(Path, "read_bytes", frozen_only),
        ):
            target = Path(directory) / "A0.zip"
            data = export_bundle(CAPTURE, None, None, target, compiler_capture=True)
            self.assertEqual(data["schemaVersion"], 2)
            self.assertIsNone(data["totals"]["allocation"])
            self.assertFalse(any(e["scope"] == "setup" for e in data["events"]))
            self.assertEqual(
                data["provenance"]["sourceSnapshotStatus"], "verified build-time bytes"
            )
            self.assertEqual(
                data["measurementSummary"]["footprint"]["executable_code"]["value"],
                "48688",
            )
            key = "build/compiler/A0/model.cc"
            self.assertEqual(
                data["sources"][key]["status"], "verified build-time snapshot"
            )
            with zipfile.ZipFile(target) as z:
                m = json.loads(z.read("manifest.json"))
                self.assertEqual(m["schemaVersion"], 2)
                for name, meta in m["files"].items():
                    raw = z.read(name)
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), meta["sha256"])
                    self.assertEqual(len(raw), meta["size"])
                    self.assertNotIn(b'"data_hex"', raw)
                self.assertFalse(
                    any(n.endswith((".bin", ".elf")) for n in z.namelist())
                )
                forbidden = self.context["evidence"]["files"][
                    "build/compiler/A0/constants.cc"
                ]["sha256"]
                self.assertNotIn(f"sources/{forbidden}.txt", z.namelist())
                saved = data["sources"][key]
                self.assertEqual(
                    hashlib.sha256(z.read(saved["archivePath"])).hexdigest(),
                    saved["sha256"],
                )
                self.assertEqual(len(data["executionPlan"]["artifacts"]), 6)

    @unittest.skipUnless(ANALYSIS.exists(), "verified local GCC analysis required")
    def test_all_executable_units_attach_and_mismatches_fail(self):
        from investigation.diagnostics import verify_analysis

        directory, analysis = verify_analysis(ANALYSIS)
        payloads = {}
        units, proof = attach_analysis(ANALYSIS, self.context, payloads)
        self.assertEqual(len(units), 5)
        self.assertTrue(proof["loadableIdentical"])
        self.assertTrue(any(u["source"].endswith("/model.cc") for u in units))
        self.assertTrue(all(len(u["artifacts"]) == 9 for u in units))
        bad = copy.deepcopy(analysis)
        bad["measured_elf_sha256"] = "0" * 64
        with (
            patch(
                "investigation.diagnostics.verify_analysis",
                return_value=(directory, bad),
            ),
            self.assertRaisesRegex(ValueError, "measured ELF"),
        ):
            attach_analysis(ANALYSIS, self.context, {})
        bad = copy.deepcopy(analysis)
        # A matching ELF cannot legitimize stale compilation dependencies.
        key = "build/compiler/A0/model.cc"
        bad["units"][0]["dependency_sha256"][key] = "0" * 64
        with (
            patch(
                "investigation.diagnostics.verify_analysis",
                return_value=(directory, bad),
            ),
            self.assertRaisesRegex(ValueError, "dependency mismatch"),
        ):
            attach_analysis(ANALYSIS, self.context, {})


if __name__ == "__main__":
    unittest.main()
