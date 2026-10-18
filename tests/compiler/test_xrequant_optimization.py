"""Validate opt-in X2 schedules, saved-plan integrity and wide ADD bounds."""

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import test_xrequant

from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.ir import ModelError
from compiler.kernel_plan import KernelPlan, select_kernels
from compiler.lowering import lower_graph
from compiler.quantization import requantize
from compiler.xrequant import (
    ADD64_CHOICE,
    OUTLINE_CHOICE,
    add_int32_bounds,
    optimization_options,
)

ROOT = Path(__file__).resolve().parents[2]


class XrequantOptimizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_xrequant.XrequantTests.setUpClass()
        base = test_xrequant.XrequantTests
        cls.graph, cls.prepared, cls.options = base.graph, base.prepared, base.options
        cls.reference = base.new
        cls.optimized = lower_graph(
            cls.graph,
            cls.prepared,
            configuration="X2",
            **cls.options,
            xrequant_depthwise_outlining="selected",
            xrequant_add_register_bits=64,
        )

    def test_exact_scope_data_preservation_and_roundtrip(self):
        nodes = self.optimized.kernels.nodes
        self.assertEqual(
            [n.node for n in nodes if OUTLINE_CHOICE in n.choices],
            [2, 8, 22, 26, 33, 37, 41, 56],
        )
        self.assertEqual(
            [n.node for n in nodes if ADD64_CHOICE in n.choices],
            [10, 17, 24, 28, 35, 39, 46, 50, 54],
        )
        for a, b in zip(self.reference.kernels.nodes, nodes):
            self.assertEqual(a, replace(b, choices=a.choices))
        self.assertEqual(self.reference.prepared, self.optimized.prepared)
        self.assertEqual(self.reference.memory, self.optimized.memory)
        self.assertEqual(
            KernelPlan.from_json(
                self.optimized.kernels.to_json(), self.graph, self.prepared
            ),
            self.optimized.kernels,
        )
        for outline, bits in (("none", 64), ("selected", 32), ("selected", 64)):
            plan = select_kernels(
                self.graph,
                self.prepared,
                "X2",
                **self.options,
                xrequant_depthwise_outlining=outline,
                xrequant_add_register_bits=bits,
            )
            self.assertEqual(
                optimization_options(plan.nodes),
                {
                    "xrequant_depthwise_outlining": outline,
                    "xrequant_add_register_bits": bits,
                },
            )
            self.assertEqual(
                KernelPlan.from_json(plan.to_json(), self.graph, self.prepared), plan
            )
        # Removing a marker from just one eligible node must not silently produce
        # a partial, misleading version of the selected policy.
        for node, marker in ((33, OUTLINE_CHOICE), (10, ADD64_CHOICE)):
            bad = json.loads(self.optimized.kernels.to_json())
            bad["nodes"][node]["choices"].remove(marker)
            with self.assertRaises(ModelError):
                KernelPlan.from_json(json.dumps(bad), self.graph, self.prepared)

    def test_bounds_cover_every_int8_input_and_reject_overflow(self):
        for node in self.prepared.nodes:
            if node.kind != "ADD":
                continue
            p = node.integers
            lo, hi = add_int32_bounds(p)
            ranges = []
            for prefix in ("input1", "input2"):
                values = [
                    requantize(
                        (x + p[prefix + "_offset"]) * (1 << p["left_shift"]),
                        p[prefix + "_multiplier"],
                        p[prefix + "_shift"],
                    )
                    for x in range(-128, 128)
                ]
                ranges.append((min(values), max(values)))
            self.assertEqual(
                (lo, hi), (sum(v[0] for v in ranges), sum(v[1] for v in ranges))
            )
            self.assertTrue(-(2**31) <= lo <= hi < 2**31)
        p = dict(self.prepared.nodes[10].integers)
        for bad in (
            {**p, "left_shift": 31},
            {**p, "input1_offset": 10000},
            {
                **p,
                "left_shift": 23,
                "input1_offset": 128,
                "input2_offset": 128,
                "input1_multiplier": 2**31 - 1,
                "input2_multiplier": 2**31 - 1,
                "input1_shift": 0,
                "input2_shift": 0,
            },
        ):
            with self.assertRaises(ModelError):
                add_int32_bounds(bad)
        for cfg in ("A0", "B1", "X1"):
            for options in (
                {"xrequant_add_register_bits": 64},
                {"xrequant_depthwise_outlining": "selected"},
            ):
                with self.assertRaisesRegex(ModelError, "require X2"):
                    select_kernels(self.graph, self.prepared, cfg, **options)

    def test_emission_manifest_and_cli_saved_policy_checks(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            path = Path(temporary)
            emit_cpp(self.optimized, path / "model")
            source = (path / "model/model.cc").read_text()
            self.assertEqual(source.count("/* OutlinePixel */ true"), 8)
            self.assertEqual(source.count("/* Accumulator */ int64_t"), 9)
            self.assertEqual(source.count("arch_project::XRequantization64"), 9)
            manifest = json.loads((path / "model/manifest.json").read_text())
            self.assertIn("kernels/xrequant/add64.h", manifest["source_sha256"])
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "X2",
                "--kernel-plan",
                str(path / "model/kernel_plan.json"),
            ]
            self.assertEqual(main([*args, "--output-dir", str(path / "saved")]), 0)
            self.assertEqual((path / "saved/model.cc").read_text(), source)
            for flag, value in (
                ("--xrequant-depthwise-outlining", "none"),
                ("--xrequant-add-register-bits", "32"),
            ):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(
                        main([*args, flag, value, "--output-dir", str(path / "bad")]), 1
                    )
                self.assertFalse((path / "bad").exists())


if __name__ == "__main__":
    unittest.main()
