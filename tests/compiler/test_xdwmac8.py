"""Depthwise correction proof, packed selection and exact native accumulators."""

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import test_xpostinc
from compiler.depthwise import BANK, ZERO, bank_counts, correction_tables
from compiler.ir import ModelError
from compiler.kernel_plan import KernelPlan, depthwise_filter_size
from compiler.lowering import lower_graph
from tools.xdwmac8.contract import NAMES, decode, encode

ROOT = Path(__file__).resolve().parents[2]


class DepthwiseBankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_xpostinc.XpostincTests.setUpClass()
        old = test_xpostinc.XpostincTests
        cls.graph, cls.prepared = old.graph, old.prepared
        cls.options = {**old.options, "xpostinc_depthwise": "selected"}
        cls.legacy = lower_graph(
            cls.graph, cls.prepared, configuration="X3", **cls.options
        )
        cls.scalar = lower_graph(
            cls.graph,
            cls.prepared,
            configuration="X3",
            depthwise_zero_point="regions",
            **cls.options,
        )
        cls.packed = lower_graph(
            cls.graph,
            cls.prepared,
            configuration="X4",
            depthwise_zero_point="regions",
            **cls.options,
        )

    def test_all_depthwise_nodes_only_and_legacy_contract(self):
        selected = []
        for a, b, c in zip(
            self.legacy.kernels.nodes,
            self.scalar.kernels.nodes,
            self.packed.kernels.nodes,
        ):
            if depthwise_filter_size(a):
                selected.append(a.node)
                self.assertIn(ZERO, b.choices)
                self.assertIn(BANK, c.choices)
                self.assertEqual(b.memory, c.memory)
                self.assertEqual(a, replace(b, memory=a.memory, choices=a.choices))
            else:
                self.assertEqual(a, b)
                self.assertEqual(a, c)
        self.assertEqual(len(selected), 16)
        self.assertEqual(self.scalar.memory.tensors, self.legacy.memory.tensors)
        self.assertEqual(self.packed.memory, self.scalar.memory)
        old = json.loads(self.legacy.kernels.to_json())
        self.assertTrue(
            all("depthwise_biases" not in n["memory"] for n in old["nodes"])
        )

    def test_region_corrections_independent_valid_tap_sum(self):
        for n in self.scalar.kernels.nodes:
            if ZERO not in n.choices:
                continue
            g = n.geometry
            _, h, w, c = g.input_shape
            _, oh, ow, _ = g.output_shape
            f = g.weight_shape[1]
            sh, sw = g.stride
            top, _, left, _ = g.padding
            node = self.graph.nodes[n.node]
            weights = self.graph.constant_values(node.input("weights"))
            biases = self.graph.constant_values(node.input("bias"))
            offset = self.prepared.nodes[n.node].input_offsets[0]
            for y, x in {
                (0, 0),
                (oh - 1, ow - 1),
                (oh // 2, ow // 2),
                (0, ow // 2),
                (oh // 2, 0),
            }:
                region = n.memory.depthwise_regions[y * ow + x]
                for ch in range(c):
                    expected = biases[ch] + sum(
                        offset * weights[(fy * f + fx) * c + ch]
                        for fy in range(f)
                        for fx in range(f)
                        if 0 <= y * sh - top + fy < h and 0 <= x * sw - left + fx < w
                    )
                    self.assertEqual(
                        n.memory.depthwise_biases[region * c + ch], expected
                    )

    def test_saved_plan_recomputes_all_tables(self):
        for model in (self.legacy, self.scalar, self.packed):
            plan = model.kernels
            self.assertEqual(
                KernelPlan.from_json(plan.to_json(), self.graph, self.prepared), plan
            )
        for field in ("depthwise_biases", "depthwise_regions"):
            bad = json.loads(self.packed.kernels.to_json())
            bad["nodes"][2]["memory"][field][0] += 1
            with self.assertRaises(ModelError):
                KernelPlan.from_json(json.dumps(bad), self.graph, self.prepared)
        bad = json.loads(self.packed.kernels.to_json())
        bad["nodes"][2]["choices"].remove(ZERO)
        with self.assertRaises(ModelError):
            KernelPlan.from_json(json.dumps(bad), self.graph, self.prepared)

    def test_overflow_proof_rejects_unrepresentable_bias(self):
        n = self.scalar.kernels.nodes[2]
        bias = self.graph.nodes[2].input("bias")
        original = type(self.graph).constant_values

        def values(graph, index):
            return (
                (2**31 - 1,) * n.geometry.input_shape[-1]
                if index == bias
                else original(graph, index)
            )

        with patch.object(type(self.graph), "constant_values", values):
            with self.assertRaisesRegex(ModelError, "INT32 prefix"):
                correction_tables(self.graph, n, self.prepared.nodes[2])

    def test_bank_counts_and_reserved_encodings(self):
        from compiler.execution_plan import reference_work

        for n in self.packed.kernels.nodes:
            counts = bank_counts(
                n, reference_work(self.graph, self.graph.nodes[n.node])
            )
            if BANK in n.choices:
                b, h, w, c = n.geometry.output_shape
                self.assertEqual(counts["xdwset0"], b * h * w * c // 8)
                self.assertEqual(counts["xdwget3"], counts["xdwset0"])
            else:
                self.assertEqual(counts, {})
        for name in NAMES:
            fields = (
                {"rs1": 31, "rs2": 31}
                if name == "xdwmac8"
                else {"rs1": 31}
                if name.startswith("xdwset")
                else {"rd": 31}
            )
            self.assertEqual(decode(encode(name, **fields)), name)
        for bits in (0x208B, 0x0200200B, 0x0800300B, 0x0010400B, 0x0000C00B):
            self.assertIsNone(decode(bits))

    def test_exact_accumulators_with_sanitizers(self):
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
            binary = Path(d) / "depthwise"
            subprocess.run(
                [
                    cxx,
                    "-std=c++17",
                    "-O1",
                    "-DARCH_PROJECT_PROJECT_NUMERICS",
                    "-fsanitize=address,undefined",
                    "-fno-sanitize-recover=all",
                    *sdk,
                    "-I",
                    str(ROOT),
                    str(ROOT / "tests/compiler/depthwise_bank_main.cc"),
                    "-o",
                    str(binary),
                ],
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                [str(binary)], check=True, capture_output=True, text=True
            )
            self.assertIn("exact accumulators", result.stdout)


if __name__ == "__main__":
    unittest.main()
