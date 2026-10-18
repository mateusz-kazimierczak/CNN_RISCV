"""Guard ownership, repeatability and source isolation of the custom RTL overlay."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.cvw.prepare_xdwmac8 import digest, prepare


class OverlayTests(unittest.TestCase):
    def test_idempotent_overlay_preserves_pinned_and_baseline_sources(self):
        source = ROOT / ".deps/cvw"
        baseline = ROOT / "build/cvw/wally-xpostinc/integration.json"
        before = digest(baseline) if baseline.exists() else None
        with (
            tempfile.TemporaryDirectory() as temporary,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            output = Path(temporary) / "overlay"
            first = prepare(source, output)
            self.assertEqual(first, prepare(source, output))
            self.assertTrue(first["rtl_modified"])
            self.assertFalse((output / "src/lsu").is_symlink())
            for mode in first["configurations"].values():
                self.assertIn("xqmac8", mode)
                self.assertIn("xrequant", mode)
                self.assertIn("xpostinc", mode)
                self.assertIn("xdwmac8", mode)
            self.assertTrue(
                first["configurations"]["arch_project_xdwmac8_only"]["xdwmac8"]
            )
            self.assertFalse(
                first["configurations"]["arch_project_xdwmac8_only"]["xqmac8"]
            )
            for name, expected in first["files_sha256"].items():
                self.assertFalse((output / name).is_symlink())
                self.assertEqual(digest(output / name), expected)
            for name, config in first["configurations"].items():
                self.assertEqual(
                    digest(output / "config" / name / "config.vh"), config["sha256"]
                )
            params = (output / "config/shared/parameter-defs.vh").read_text()
            self.assertIn("32'h00800000", params)
            self.assertIn("XLEN == 64", params)
            self.assertEqual(
                (output / "src/ieu/xqmac8.sv").read_bytes(),
                (ROOT / "rtl/cvw/xqmac8.sv").read_bytes(),
            )
        self.assertEqual(
            subprocess.check_output(["git", "-C", source, "diff", "HEAD", "--"]), b""
        )
        if before:
            self.assertEqual(digest(baseline), before)

    def test_decode_matches_independent_isa_contract(self):
        import random
        from tools.xdwmac8.contract import decode

        rng = random.Random(0x4457435657)
        for bits in [rng.getrandbits(32) for _ in range(10000)] + [
            (funct7 << 25)
            | (rs2 << 20)
            | (rs1 << 15)
            | (funct3 << 12)
            | (rd << 7)
            | 0x0B
            for funct7 in range(128)
            for funct3 in range(8)
            for rd in (0, 1, 31)
            for rs1 in (0, 1, 31)
            for rs2 in (0, 1, 31)
        ]:
            expected = decode(bits)
            hardware = (
                (bits & 0xFE007FFF) == 0x200B
                or (bits & 0xF9F07FFF) == 0x300B
                or (bits & 0xF9FFF07F) == 0x400B
            )
            self.assertEqual(hardware, expected is not None)

    def test_refuses_to_discard_changed_rtl(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            output = Path(temporary) / "overlay"
            prepare(ROOT / ".deps/cvw", output)
            path = output / "src/ieu/controller.sv"
            changed = path.read_bytes() + b"\n// local experiment\n"
            path.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, "preserve modified overlay"):
                prepare(ROOT / ".deps/cvw", output)
            self.assertEqual(path.read_bytes(), changed)

    def test_refuses_to_discard_changed_configuration(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            output = Path(temporary) / "overlay"
            prepare(ROOT / ".deps/cvw", output)
            path = output / "config/arch_project_xdwmac8/config.vh"
            changed = path.read_bytes() + b"\n// local experiment\n"
            path.write_bytes(changed)
            with self.assertRaisesRegex(
                ValueError, "preserve modified overlay configuration"
            ):
                prepare(ROOT / ".deps/cvw", output)
            self.assertEqual(path.read_bytes(), changed)

    def test_refuses_unrelated_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            path = output / "integration.json"
            original = json.dumps({"rtl_modified": False}).encode()
            path.write_bytes(original)
            with self.assertRaisesRegex(ValueError, "unrelated overlay"):
                prepare(ROOT / ".deps/cvw", output)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
