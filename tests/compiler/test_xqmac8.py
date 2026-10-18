"""X1 selection, canonical plan validation, and custom-opcode decoding."""

import json
import contextlib
import io
import tempfile
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from compiler.frontend import import_model
from compiler.kernel_plan import (
    KernelPlan,
    select_kernels,
    validate_kernel_plan,
    pointwise_block_size,
)
from compiler.lowering import lower_graph
from compiler.quantization import prepare_graph
from compiler.ir import ModelError
from tools.xqmac8.runtime import decode
from tools.xqmac8.vectors import oracle
from compiler.cli import main


class Xqmac8Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        cls.prepared = prepare_graph(cls.graph)
        cls.options = dict(
            runtime="standalone",
            stem_unroll=True,
            depthwise_kernels=(3, 5),
            pointwise_pixels=2,
            pointwise_block=2,
            requantization="nonpositive",
            requantization_overrides={
                n: "inline-nonpositive"
                for n in (
                    1,
                    2,
                    3,
                    4,
                    5,
                    6,
                    7,
                    8,
                    9,
                    11,
                    12,
                    14,
                    15,
                    18,
                    19,
                    20,
                    21,
                    22,
                    25,
                    26,
                    29,
                    41,
                    44,
                    48,
                    52,
                )
            },
        )
        cls.b1 = select_kernels(cls.graph, cls.prepared, "B1", **cls.options)
        cls.x1 = select_kernels(cls.graph, cls.prepared, "X1", **cls.options)

    def test_only_pointwise_reduction_changes(self):
        count = 0
        for old, new in zip(self.b1.nodes, self.x1.nodes):
            self.assertEqual(old.memory, new.memory)
            if pointwise_block_size(old):
                count += 1
                self.assertEqual(new.reduction_backend, "xqmac8_spatial2")
                self.assertEqual(
                    replace(
                        new,
                        reduction_backend=old.reduction_backend,
                        arithmetic_backend=old.arithmetic_backend,
                        choices=old.choices,
                    ),
                    old,
                )
            else:
                self.assertEqual(old, new)
        self.assertEqual(count, 32)

    def test_physical_memory_plan_unchanged(self):
        old = lower_graph(self.graph, self.prepared, kernels=self.b1)
        new = lower_graph(self.graph, self.prepared, kernels=self.x1)
        self.assertEqual(old.memory, new.memory)

    def test_plan_roundtrip_and_forgery(self):
        self.assertEqual(
            KernelPlan.from_json(self.x1.to_json(), self.graph, self.prepared), self.x1
        )
        bad = json.loads(self.x1.to_json())
        bad["nodes"][4]["reduction_backend"] = "scalar_dot8_spatial2"
        with self.assertRaises(ModelError):
            KernelPlan.from_json(json.dumps(bad), self.graph, self.prepared)
        with self.assertRaises(ModelError):
            validate_kernel_plan(
                replace(self.x1, configuration="B1"), self.graph, self.prepared
            )

    def test_exact_decoder_mask(self):
        for rd in range(32):
            for rs1 in range(32):
                for rs2 in range(32):
                    self.assertTrue(decode(0xB | rd << 7 | rs1 << 15 | rs2 << 20, 4))
        for bit in (*range(7), *range(12, 15), *range(25, 32)):
            self.assertFalse(decode(0xB ^ (1 << bit), 4))
        self.assertFalse(decode(0xB, 2))

    def test_cli_defaults_match_accepted_software_selection(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                main(
                    [
                        "generate",
                        str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                        "--config",
                        "X1",
                        "--output-dir",
                        temporary,
                    ]
                ),
                0,
            )
            saved = KernelPlan.from_json(
                (Path(temporary) / "kernel_plan.json").read_text(),
                self.graph,
                self.prepared,
            )
            self.assertEqual(saved, self.x1)

    def test_oracle_wrapping_and_lane_pairing(self):
        self.assertEqual(oracle(0, 0x80, 0x7F), (-16256) & ((1 << 64) - 1))
        self.assertEqual(oracle(0x7FFFFFFF, 1, 1), 0xFFFFFFFF80000000)
        self.assertEqual(oracle(0xDEADBEEF00000001, 1, 1), 2)
        self.assertEqual(oracle(0, 0x80, 0x7F00), 0)


if __name__ == "__main__":
    unittest.main()
