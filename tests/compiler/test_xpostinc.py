"""X3 schedule, memory provenance, exact decoding and profile classification."""

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import test_xrequant_optimization

from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.ir import ModelError
from compiler.kernel_plan import (
    KernelPlan,
    depthwise_filter_size,
    pointwise_block_size,
    select_kernels,
)
from compiler.lowering import lower_graph
from compiler.xpostinc import DEPTHWISE, POINTWISE, expected_counts
from tools.xpostinc.contract import LOADS, STORES, decode, encode, load_oracle
from tools.xqmac8.analysis import classify

ROOT = Path(__file__).resolve().parents[2]


class XpostincTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_xrequant_optimization.XrequantOptimizationTests.setUpClass()
        old = test_xrequant_optimization.XrequantOptimizationTests
        cls.graph, cls.prepared = old.graph, old.prepared
        cls.parent = old.optimized
        cls.options = {
            **old.options,
            "xrequant_depthwise_outlining": "selected",
            "xrequant_add_register_bits": 64,
        }
        cls.model = lower_graph(
            cls.graph, cls.prepared, configuration="X3", **cls.options
        )

    def test_only_memory_policy_changes_and_roundtrip(self):
        self.assertEqual(self.parent.prepared, self.model.prepared)
        self.assertEqual(self.parent.memory, self.model.memory)
        for a, b in zip(self.parent.kernels.nodes, self.model.kernels.nodes):
            self.assertEqual(a, replace(b, choices=a.choices))
            marker = (
                POINTWISE
                if pointwise_block_size(b)
                else DEPTHWISE
                if depthwise_filter_size(b)
                else None
            )
            self.assertEqual(b.choices, (*a.choices, marker) if marker else a.choices)
        plan = self.model.kernels
        self.assertEqual(
            KernelPlan.from_json(plan.to_json(), self.graph, self.prepared), plan
        )
        for node in (4, 8):
            bad = json.loads(plan.to_json())
            bad["nodes"][node]["choices"].pop()
            with self.assertRaises(ModelError):
                KernelPlan.from_json(json.dumps(bad), self.graph, self.prepared)
        with self.assertRaisesRegex(ModelError, "8-byte"):
            select_kernels(
                self.graph,
                self.prepared,
                "X3",
                **{**self.options, "xqmac8_weight_alignment": 4},
            )
        with self.assertRaisesRegex(ModelError, "blocked"):
            select_kernels(
                self.graph,
                self.prepared,
                "X3",
                **{**self.options, "pointwise_block": 1, "pointwise_pixels": 1},
            )

    def test_independent_schedule_counts_include_borders_and_tail(self):
        from compiler.execution_plan import reference_work

        for n in self.model.kernels.nodes:
            work = reference_work(self.graph, self.graph.nodes[n.node])
            counts = expected_counts(n, work)
            if DEPTHWISE in n.choices:
                g = n.geometry
                b, h, w, c = g.input_shape
                _, oh, ow, _ = g.output_shape
                f = depthwise_filter_size(n)
                sh, sw = g.stride
                top, _, left, _ = g.padding
                taps = 0
                for y in range(oh):
                    for x in range(ow):
                        oy, ox = y * sh - top, x * sw - left
                        if 0 <= oy and oy + f <= h and 0 <= ox and ox + f <= w:
                            continue
                        taps += sum(
                            0 <= oy + fy < h and 0 <= ox + fx < w
                            for fy in range(f)
                            for fx in range(f)
                        )
                self.assertEqual(
                    counts, {"load": 2 * taps * b * c, "store": b * oh * ow * c}
                )
            elif POINTWISE in n.choices:
                g = n.geometry
                pixels = g.output_shape[0] * g.output_shape[1] * g.output_shape[2]
                self.assertEqual(
                    counts["load"],
                    ((pixels + 1) // 2)
                    * (g.output_shape[-1] // 4)
                    * (g.input_shape[-1] // 8)
                    * 2,
                )
                self.assertEqual(counts["store"], (pixels % 2) * g.output_shape[-1])
            else:
                self.assertEqual(counts, {"load": 0, "store": 0})

    def test_selected_policy_retains_only_measured_depthwise_geometries(self):
        from compiler.xpostinc import NONE, SELECTED, depthwise_policy

        for mode, wanted in (("selected", [2, 5, 8, 22, 26, 56]), ("none", [])):
            model = lower_graph(
                self.graph,
                self.prepared,
                configuration="X3",
                xpostinc_depthwise=mode,
                **self.options,
            )
            self.assertEqual(
                [n.node for n in model.kernels.nodes if DEPTHWISE in n.choices], wanted
            )
            self.assertEqual(depthwise_policy(model.kernels.nodes), mode)
            self.assertEqual(
                KernelPlan.from_json(
                    model.kernels.to_json(), self.graph, self.prepared
                ),
                model.kernels,
            )
            for node in model.kernels.nodes:
                if depthwise_filter_size(node):
                    self.assertIn(
                        SELECTED if mode == "selected" else NONE, node.choices
                    )
            self.assertEqual(model.memory, self.parent.memory)

    def test_encoding_signed_immediate_and_memory_classification(self):
        for name in (*LOADS, *STORES):
            for stride in (-2048, -1, 0, 1, 2047):
                for value, base in ((0, 0), (0, 31), (31, 0), (5, 6), (31, 31)):
                    bits = encode(name, value, base, stride)
                    self.assertEqual(decode(bits), name)
                    self.assertIsNone(decode(bits, 2))
                    self.assertEqual(bits >> 20, stride & 4095)
            self.assertEqual(classify(name), "load" if name in LOADS else "store")
        self.assertIsNone(decode(0x702B))
        for f in range(4, 8):
            self.assertIsNone(decode(0x7B | (f << 12)))
        for n in (-2049, 2048):
            with self.assertRaises(ValueError):
                encode("xldpi", 5, 6, n)
        self.assertEqual(load_oracle("xlbpi", b"\x80"), (1 << 64) - 128)
        self.assertEqual(load_oracle("xlbupi", b"\x80"), 128)
        self.assertEqual(load_oracle("xlwupi", b"\xff" * 4), (1 << 32) - 1)

    def test_emission_manifest_defaults_and_saved_policy(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            root = Path(temp)
            manifest = emit_cpp(self.model, root / "explicit")
            emit_cpp(self.parent, root / "parent")
            for name in (
                "constants.cc",
                "constants.h",
                "prepared_ir.json",
                "memory_plan.json",
            ):
                self.assertEqual(
                    (root / "explicit" / name).read_bytes(),
                    (root / "parent" / name).read_bytes(),
                )
            self.assertEqual(
                manifest["isa_extensions"], ["xqmac8", "xrequant", "xpostinc"]
            )
            self.assertIn("kernels/xpostinc/memory.h", manifest["source_sha256"])
            self.assertEqual(manifest["stage"], 10)
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "X3",
            ]
            self.assertEqual(main([*args, "--output-dir", str(root / "default")]), 0)
            self.assertEqual(
                (root / "default/model.cc").read_text(),
                (root / "explicit/model.cc").read_text(),
            )
            saved = [*args, "--kernel-plan", str(root / "default/kernel_plan.json")]
            self.assertEqual(main([*saved, "--output-dir", str(root / "saved")]), 0)
            self.assertEqual(
                (root / "saved/model.cc").read_text(),
                (root / "default/model.cc").read_text(),
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            *saved,
                            "--xrequant-add-register-bits",
                            "32",
                            "--output-dir",
                            str(root / "bad"),
                        ]
                    ),
                    1,
                )
            self.assertFalse((root / "bad").exists())


if __name__ == "__main__":
    unittest.main()
