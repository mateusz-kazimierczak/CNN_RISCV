"""Stage 0 gates: unchanged B0, real native tensors, repeatability and diagnostics."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from compiler.cli import main
from compiler.oracle import compare_captures, sha, verify_capture, verify_golden
from compiler.reference_inputs import CASES, INPUT_BYTES, fnv1a, lcg_bytes
from tools.capture_tflm_oracle import capture
from tools.freeze_compiler_baseline import archive_name, verify_files

FIXTURES = ROOT / "tests/compiler/fixtures"
GOLDEN = FIXTURES / "oracle-golden.json"


class InputAndCommandTests(unittest.TestCase):
    def test_baseline_sequence_and_complete_input_hash(self):
        data = lcg_bytes(INPUT_BYTES)
        self.assertEqual(list(data[:16]), [60, 94, 129, 180, 12, 94, 198, 142, 4, 163, 64, 108, 151, 214, 60, 251])
        self.assertEqual(hashlib.sha256(data).hexdigest(), "656c4935ee43649bf2d57b7b82e4394ea1c9a528b6c0c63148b8c787362d976b")

    def test_invalid_input_configuration(self):
        for size, seed in ((-1, 1), (1, -1), (1, 1 << 32)):
            with self.subTest(size=size, seed=seed), self.assertRaises(ValueError):
                lcg_bytes(size, seed)

    def test_golden_output_is_complete_and_matches_b0(self):
        data = (FIXTURES / "baseline-output.bin").read_bytes()
        self.assertEqual(len(data), 1000)
        self.assertEqual(fnv1a(data), "0x4b6a91e2")
        self.assertEqual((data.index(max(data)), max(data), sum(data)), (21, 48, 215))

    def test_codegen_rejects_future_backend(self):
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as error:
                main(["generate", "models/efficientnet-lite0-int8.tflite", "--config", "X6"])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("invalid choice", errors.getvalue())


class BaselineTests(unittest.TestCase):
    def test_b0_files_match_frozen_hashes(self):
        contract = json.loads((ROOT / "tools/compiler/baseline.json").read_text())
        verify_files(ROOT, contract["frozen_files"])

    def test_archive_is_complete_and_cannot_register_make_targets(self):
        root = ROOT / "build/compiler/baseline/B0"
        contract = json.loads((ROOT / "tools/compiler/baseline.json").read_text())
        archive = json.loads((root / "archive.json").read_text())
        self.assertEqual(archive["contract_sha256"], sha(ROOT / "tools/compiler/baseline.json"))
        verify_files(root, contract["frozen_files"], archived=True)
        self.assertEqual(list(root.rglob("Makefile_internal.inc")), [])
        self.assertTrue((root / archive_name("tflm/Makefile_internal.inc")).is_file())


class OracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pointer = ROOT / "build/compiler/oracle/latest.json"
        if not pointer.exists():
            raise RuntimeError("reference capture missing; run gmake compiler-oracle first")
        cls.directory = Path(json.loads(pointer.read_text())["capture"])
        cls.manifest = verify_golden(cls.directory, GOLDEN)
        cls.record = json.loads((ROOT / "build/compiler/oracle-build.json").read_text())

    def test_all_reference_arrays_match_committed_golden(self):
        self.assertEqual(len(self.manifest["cases"]), 8)
        self.assertEqual(sum(len(case["tensors"]) for case in self.manifest["cases"]), 510)
        self.assertEqual(sum(case["returncode"] == 0 for case in self.manifest["cases"]), 7)
        self.assertEqual(
            (self.directory / "baseline/output.bin").read_bytes(),
            (FIXTURES / "baseline-output.bin").read_bytes(),
        )

    def test_both_boundary_conversions_match_every_byte(self):
        for case in self.manifest["cases"]:
            with self.subTest(case=case["name"]):
                root = self.directory / case["name"]
                first = (root / case["tensors"][0]["file"]).read_bytes()
                self.assertEqual(first, bytes((value - 128) & 255 for value in (root / "input.bin").read_bytes()))
                if case["returncode"] == 0:
                    softmax = (root / case["tensors"][62]["file"]).read_bytes()
                    self.assertEqual((root / "output.bin").read_bytes(), bytes((value + 128) & 255 for value in softmax))

    def test_representative_full_tensor_shapes(self):
        tensors = self.manifest["cases"][0]["tensors"]
        for node, shape in ((1, [1, 112, 112, 32]), (4, [1, 112, 112, 96]),
                            (8, [1, 56, 56, 144]), (15, [1, 28, 28, 240]),
                            (58, [1, 7, 7, 1280]), (61, [1, 1000])):
            with self.subTest(node=node):
                self.assertEqual(tensors[node]["shape"], shape)
                path = self.directory / "baseline" / tensors[node]["file"]
                self.assertEqual(path.stat().st_size, tensors[node]["bytes"])

    def test_full_capture_repeats_byte_for_byte(self):
        with tempfile.TemporaryDirectory(prefix="compiler-oracle-repeat-") as temporary:
            with contextlib.redirect_stdout(io.StringIO()):
                repeated = capture(Path(temporary), self.record, reuse=False)
            compare_captures(self.directory, repeated)

    def test_original_memory_reuse_also_matches_or_aborts(self):
        binary = ROOT / self.record["binary"]
        with tempfile.TemporaryDirectory(prefix="compiler-oracle-normal-") as temporary:
            for expected, case in zip(CASES, self.manifest["cases"]):
                with self.subTest(case=case["name"]):
                    directory = Path(temporary) / case["name"]
                    directory.mkdir()
                    result = subprocess.run([
                        str(binary), str(self.directory / case["name"] / "input.bin"),
                        str(directory), "--no-preserve",
                    ], check=False, capture_output=True, text=True)
                    self.assertEqual(result.returncode, -signal.SIGABRT if expected.expected_signal else 0)
                    if expected.expected_signal is None:
                        self.assertEqual((directory / "output.bin").read_bytes(),
                                         (self.directory / case["name"] / "output.bin").read_bytes())
                        self.assertIn("arena_used_bytes=1688176", result.stdout)
                    else:
                        self.assertFalse((directory / "output.bin").exists())

    def test_native_rejects_short_or_oversized_public_input(self):
        with tempfile.TemporaryDirectory(prefix="compiler-oracle-invalid-") as temporary:
            root = Path(temporary)
            for size in (INPUT_BYTES - 1, INPUT_BYTES + 1):
                with self.subTest(size=size):
                    source = root / "input.bin"
                    source.write_bytes(bytes(size))
                    result = subprocess.run([str(ROOT / self.record["binary"]), str(source), str(root)], check=False, capture_output=True)
                    self.assertEqual(result.returncode, 7)
                    self.assertFalse((root / "output.bin").exists())

    def test_detects_changed_tensor_and_reports_first_divergence(self):
        with tempfile.TemporaryDirectory(prefix="compiler-oracle-corrupt-") as temporary:
            candidate = Path(temporary) / "capture"
            shutil.copytree(self.directory, candidate)
            manifest = json.loads((candidate / "manifest.json").read_text())
            case = manifest["cases"][0]
            tensor = case["tensors"][4]
            path = candidate / case["name"] / tensor["file"]
            data = bytearray(path.read_bytes())
            data[17] ^= 1
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "missing or changed artifact"):
                verify_capture(candidate)
            # An internally consistent candidate still must fail the independent comparison.
            tensor["sha256"] = case["files"][tensor["file"]] = sha(path)
            (candidate / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "first divergent node 4.*byte 17"):
                compare_captures(self.directory, candidate)
            with self.assertRaisesRegex(ValueError, "first divergent node 4"):
                verify_golden(candidate, GOLDEN)

    def test_rejects_incomplete_node_sequence(self):
        with tempfile.TemporaryDirectory(prefix="compiler-oracle-incomplete-") as temporary:
            candidate = Path(temporary) / "capture"
            shutil.copytree(self.directory, candidate)
            manifest = json.loads((candidate / "manifest.json").read_text())
            manifest["cases"][0]["tensors"].pop(10)
            (candidate / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "incomplete or reordered"):
                verify_capture(candidate)


if __name__ == "__main__":
    unittest.main()
