"""X5 selection, offline layout, padded work, border corrections and arithmetic."""

import contextlib
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import test_xdwmac8
from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.ir import ModelError
from compiler.kernel_plan import KernelPlan
from compiler.lowering import lower_graph
from compiler.stem import STEM, stem_tables

ROOT = Path(__file__).resolve().parents[2]


class PackedStemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_xdwmac8.DepthwiseBankTests.setUpClass()
        old = test_xdwmac8.DepthwiseBankTests
        cls.graph, cls.prepared, cls.old = old.graph, old.prepared, old.packed
        cls.model = lower_graph(
            cls.graph,
            cls.prepared,
            configuration="X5",
            depthwise_zero_point="regions",
            **old.options,
        )

    def test_only_stem_changes_and_original_data_preserved(self):
        self.assertEqual(self.old.prepared, self.model.prepared)
        self.assertEqual(self.old.memory.tensors, self.model.memory.tensors)
        self.assertEqual(self.old.memory.arena_bytes, self.model.memory.arena_bytes)
        for a, b in zip(self.old.kernels.nodes, self.model.kernels.nodes):
            if a.node == 1:
                self.assertIn(STEM, b.choices)
                self.assertEqual(len(b.memory.stem_weights), 32 * 8)
            else:
                self.assertEqual(a, b)
        self.assertEqual(
            KernelPlan.from_json(
                self.model.kernels.to_json(), self.graph, self.prepared
            ),
            self.model.kernels,
        )
        self.assertTrue(
            all(
                "stem_weights" not in n["memory"]
                for n in json.loads(self.old.kernels.to_json())["nodes"]
            )
        )

    def test_weights_and_every_border_correction_independent(self):
        n = self.model.kernels.nodes[1]
        g = n.geometry
        weights = self.graph.constant_values(self.graph.nodes[1].input("weights"))
        original = self.graph.constant_values(self.graph.nodes[1].input("bias"))
        raw = struct.pack(
            "<" + "i" * len(n.memory.stem_weights), *n.memory.stem_weights
        )
        for c in range(32):
            self.assertEqual(
                raw[c * 32 : c * 32 + 27],
                bytes(v & 255 for v in weights[c * 27 : (c + 1) * 27]),
            )
            self.assertEqual(raw[c * 32 + 27 : (c + 1) * 32], bytes(5))
        _, h, w, _ = g.input_shape
        _, oh, ow, c = g.output_shape
        top, _, left, _ = g.padding
        for y, x in {
            (0, 0),
            (oh - 1, ow - 1),
            (oh - 1, ow // 2),
            (oh // 2, ow - 1),
            (oh // 2, ow // 2),
        }:
            r = n.memory.stem_regions[y * ow + x]
            for ch in range(c):
                expected = original[ch] + self.prepared.nodes[1].input_offsets[0] * sum(
                    weights[ch * 27 + (fy * 3 + fx) * 3 + ic]
                    for fy in range(3)
                    for fx in range(3)
                    for ic in range(3)
                    if 0 <= 2 * y - top + fy < h and 0 <= 2 * x - left + fx < w
                )
                self.assertEqual(n.memory.stem_biases[r * c + ch], expected)
        for name in ("stem_biases", "stem_weights", "xrequant_descriptors"):
            offset = next(
                o for k, o, _ in self.model.memory.parameters[1].fields if k == name
            )
            self.assertEqual((self.model.memory.parameters[1].offset + offset) % 8, 0)

    def test_forged_tables_and_overflow_rejected(self):
        for field in ("stem_biases", "stem_regions", "stem_weights"):
            bad = json.loads(self.model.kernels.to_json())
            bad["nodes"][1]["memory"][field][0] += 1
            with self.assertRaises(ModelError):
                KernelPlan.from_json(json.dumps(bad), self.graph, self.prepared)
        bias = self.graph.nodes[1].input("bias")
        original = type(self.graph).constant_values

        def values(g, index):
            return (2**31 - 1,) * 32 if index == bias else original(g, index)

        with patch.object(type(self.graph), "constant_values", values):
            with self.assertRaisesRegex(ModelError, "INT32 prefix"):
                stem_tables(
                    self.graph, self.model.kernels.nodes[1], self.prepared.nodes[1]
                )
        n = self.model.kernels.nodes[1]
        with self.assertRaises(ModelError):
            stem_tables(
                self.graph,
                replace(n, geometry=replace(n.geometry, stride=(1, 1))),
                self.prepared.nodes[1],
            )

    def test_codegen_counts_and_saved_cli(self):
        with (
            tempfile.TemporaryDirectory() as d,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            root = Path(d)
            manifest = emit_cpp(self.model, root / "direct")
            self.assertEqual(manifest["stage"], 12)
            self.assertEqual(
                manifest["isa_extensions"],
                ["xqmac8", "xrequant", "xpostinc", "xdwmac8"],
            )
            plan = json.loads((root / "direct/execution_plan.json").read_text())
            work = plan["units"][1]["work"]
            self.assertEqual(work["executed_products"], 112 * 112 * 32 * 32)
            self.assertEqual(work["executed_products"] // 8, 1605632)
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "X5",
                "--kernel-plan",
                str(root / "direct/kernel_plan.json"),
                "--output-dir",
                str(root / "saved"),
            ]
            self.assertEqual(main(args), 0)
            self.assertEqual(
                (root / "direct/model.cc").read_bytes(),
                (root / "saved/model.cc").read_bytes(),
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([*args, "--depthwise-zero-point", "none"]), 1)

    def test_native_exact_accumulators_under_sanitizers(self):
        cxx = (
            "/Library/Developer/CommandLineTools/usr/bin/clang++"
            if sys.platform == "darwin"
            else "c++"
        )
        sdk = (
            ["-isysroot", "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"]
            if sys.platform == "darwin"
            else []
        )
        with tempfile.TemporaryDirectory() as d:
            binary = Path(d) / "stem"
            subprocess.run(
                [
                    cxx,
                    "-std=c++17",
                    "-O1",
                    "-fsanitize=address,undefined",
                    "-fno-sanitize-recover=all",
                    *sdk,
                    "-I",
                    str(ROOT),
                    str(ROOT / "tests/compiler/stem_packed_main.cc"),
                    "-o",
                    str(binary),
                ],
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                [str(binary)], check=True, text=True, capture_output=True
            )
            self.assertIn("64 exact accumulator cases", result.stdout)


if __name__ == "__main__":
    unittest.main()
