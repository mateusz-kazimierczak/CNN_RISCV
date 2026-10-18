"""The X1 register-width option preserves ISA math, memory and saved-plan checks."""

import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest

from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.ir import ModelError
from compiler.kernel_plan import (
    KernelPlan,
    XQMAC8_ACCUMULATOR_CHOICE,
    select_kernels,
    validate_pointwise_request,
    xqmac8_accumulator_bits,
)
from compiler.lowering import lower_graph
import test_xqmac8

ROOT = Path(__file__).resolve().parents[2]


class AccumulatorRegisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_xqmac8.Xqmac8Tests.setUpClass()
        cls.graph = test_xqmac8.Xqmac8Tests.graph
        cls.prepared = test_xqmac8.Xqmac8Tests.prepared
        cls.options = {**test_xqmac8.Xqmac8Tests.options, "xqmac8_weight_alignment": 8}
        cls.old = lower_graph(
            cls.graph, cls.prepared, configuration="X1", **cls.options
        )
        cls.new = lower_graph(
            cls.graph,
            cls.prepared,
            configuration="X1",
            xqmac8_accumulator_bits=64,
            **cls.options,
        )

    def test_only_register_representation_changes(self):
        self.assertEqual(self.old.memory, self.new.memory)
        self.assertEqual(xqmac8_accumulator_bits(self.old.kernels), 32)
        self.assertEqual(xqmac8_accumulator_bits(self.new.kernels), 64)
        selected = 0
        for old, new in zip(self.old.kernels.nodes, self.new.kernels.nodes):
            if new.reduction_backend.startswith("xqmac8"):
                selected += 1
                self.assertIn(XQMAC8_ACCUMULATOR_CHOICE, new.choices)
                self.assertEqual(replace(new, choices=old.choices), old)
            else:
                self.assertEqual(old, new)
        self.assertEqual(selected, 32)
        validate_pointwise_request(
            self.new.kernels, self.graph, self.prepared, block=2, pixels=2
        )

    def test_emission_and_canonical_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            emit_cpp(self.old, root / "old")
            emit_cpp(self.new, root / "new")
            for name in (
                "constants.cc",
                "constants.h",
                "memory_plan.json",
                "prepared_ir.json",
            ):
                self.assertEqual(
                    (root / "old" / name).read_bytes(),
                    (root / "new" / name).read_bytes(),
                )
            self.assertEqual(
                (root / "new/model.cc")
                .read_text()
                .count("Qmac8SpatialBlock<8, 8, 64>"),
                32,
            )
            self.assertEqual(
                KernelPlan.from_json(
                    self.new.kernels.to_json(), self.graph, self.prepared
                ),
                self.new.kernels,
            )

    def test_invalid_register_options_mixed_choices_and_conflicts(self):
        for config, value in (("B1", 64), ("A0", 64), ("X1", 16), ("X1", True)):
            with (
                self.subTest(config=config, value=value),
                self.assertRaises(ModelError),
            ):
                select_kernels(
                    self.graph, self.prepared, config, xqmac8_accumulator_bits=value
                )
        with self.assertRaises(ModelError):
            lower_graph(
                self.graph, kernels=self.new.kernels, xqmac8_accumulator_bits=32
            )
        forged = json.loads(self.new.kernels.to_json())
        forged["nodes"][4]["choices"].remove(XQMAC8_ACCUMULATOR_CHOICE)
        with self.assertRaises(ModelError):
            KernelPlan.from_json(json.dumps(forged), self.graph, self.prepared)

    def test_saved_cli_roundtrip_and_conflict(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            root = Path(temporary)
            plan = root / "kernel_plan.json"
            plan.write_text(self.new.kernels.to_json())
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "X1",
                "--kernel-plan",
                str(plan),
            ]
            self.assertEqual(main([*args, "--output-dir", str(root / "saved")]), 0)
            self.assertEqual(
                (root / "saved/kernel_plan.json").read_text(),
                self.new.kernels.to_json(),
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            *args,
                            "--xqmac8-accumulator-bits",
                            "32",
                            "--output-dir",
                            str(root / "bad"),
                        ]
                    ),
                    1,
                )
            self.assertFalse((root / "bad").exists())
