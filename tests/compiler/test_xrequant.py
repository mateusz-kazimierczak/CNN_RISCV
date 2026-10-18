"""X2 selection, descriptor layout, exact semantics and saved-plan validation."""

from dataclasses import replace
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from compiler.cli import main
from compiler.frontend import import_model
from compiler.kernel_plan import KernelPlan, select_kernels, parameter_values
from compiler.lowering import lower_graph
from compiler.ir import ModelError
from compiler.quantization import prepare_graph, requantize
from tools.xrequant.contract import pack, unpack, oracle, decode
import test_xqmac8

ROOT = Path(__file__).resolve().parents[2]


class XrequantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_xqmac8.Xqmac8Tests.setUpClass()
        cls.graph = test_xqmac8.Xqmac8Tests.graph
        cls.prepared = test_xqmac8.Xqmac8Tests.prepared
        cls.options = {
            **test_xqmac8.Xqmac8Tests.options,
            "pointwise_block": 4,
            "xqmac8_weight_alignment": 8,
            "xqmac8_accumulator_bits": 64,
        }
        cls.old = lower_graph(
            cls.graph, cls.prepared, configuration="X1", **cls.options
        )
        cls.new = lower_graph(
            cls.graph, cls.prepared, configuration="X2", **cls.options
        )

    def test_only_requantization_backend_changes(self):
        selected = 0
        for a, b in zip(self.old.kernels.nodes, self.new.kernels.nodes):
            if a.kind in ("CONV_2D", "DEPTHWISE_CONV_2D", "ADD", "FULLY_CONNECTED"):
                selected += 1
                self.assertEqual(b.requantization_backend, "xrequant_v1")
                self.assertEqual(
                    replace(
                        b,
                        requantization_backend=a.requantization_backend,
                        choices=a.choices,
                        memory=a.memory,
                    ),
                    a,
                )
            else:
                self.assertEqual(a, b)
        self.assertEqual(selected, 59)
        self.assertEqual(self.old.prepared, self.new.prepared)
        self.assertEqual(self.old.memory.tensors, self.new.memory.tensors)
        self.assertEqual(self.old.memory.arena_bytes, self.new.memory.arena_bytes)
        self.assertEqual(
            KernelPlan.from_json(self.new.kernels.to_json(), self.graph, self.prepared),
            self.new.kernels,
        )
        with self.assertRaises(ModelError):
            KernelPlan.from_json(
                replace(self.new.kernels, configuration="X1").to_json(),
                self.graph,
                self.prepared,
            )

    def test_packed_parameters_are_aligned_and_replace_the_two_arrays(self):
        count = 0
        for n, p, mem in zip(
            self.new.kernels.nodes, self.prepared.nodes, self.new.memory.parameters
        ):
            if n.memory.parameter_format != "xrequant_v1":
                continue
            count += 1
            values = parameter_values(p, n.memory)
            self.assertNotIn("multipliers", values)
            self.assertNotIn("shifts", values)
            offset = next(
                o for name, o, _ in mem.fields if name == "xrequant_descriptors"
            )
            self.assertEqual((mem.offset + offset) % 8, 0)
            words = values["xrequant_descriptors"]
            for ch, (m, s) in enumerate(
                zip(p.integers["multipliers"], p.integers["shifts"])
            ):
                d = (words[2 * ch] & 0xFFFFFFFF) | (
                    (words[2 * ch + 1] & 0xFFFFFFFF) << 32
                )
                self.assertEqual(
                    unpack(d),
                    (
                        m,
                        -s,
                        p.output_offset,
                        p.integers["output_activation_min"],
                        p.integers["output_activation_max"],
                        False,
                    ),
                )
        self.assertEqual(count, 49)

    def test_rounding_bounds_and_invalid_descriptors(self):
        self.assertEqual(oracle(1, pack(1 << 30, -1, -0, -128, 127)), 1)
        for x in (-(2**31), -3, -1, 0, 1, 3, 2**31 - 1):
            for m in (0, 1, 1 << 30, 2**31 - 1):
                for s in range(-31, 1):
                    expected = requantize(x, m, s) & ((1 << 64) - 1)
                    self.assertEqual(oracle(x, pack(m, s, scale_only=True)), expected)
        for d in (1 << 63, 1 << 31, 32 << 32, (1 << 62) | (1 << 38), 1 << 46):
            with self.assertRaises(ValueError):
                unpack(d)
        for s in (1, -32):
            with self.assertRaises(ValueError):
                pack(1, s)
        for bit in (*range(7), *range(12, 15), *range(25, 32)):
            self.assertFalse(decode(0x100B ^ (1 << bit), 4))
        self.assertFalse(decode(0x100B, 2))

    def test_cli_default_and_saved_plan_reconstruction(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            root = Path(temporary)
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "X2",
            ]
            self.assertEqual(main([*args, "--output-dir", str(root / "first")]), 0)
            self.assertEqual(
                (root / "first/kernel_plan.json").read_text(),
                self.new.kernels.to_json(),
            )
            self.assertEqual(
                main(
                    [
                        *args,
                        "--kernel-plan",
                        str(root / "first/kernel_plan.json"),
                        "--output-dir",
                        str(root / "saved"),
                    ]
                ),
                0,
            )
            self.assertEqual(
                (root / "first/model.cc").read_bytes(),
                (root / "saved/model.cc").read_bytes(),
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            *args,
                            "--kernel-plan",
                            str(root / "first/kernel_plan.json"),
                            "--xqmac8-accumulator-bits",
                            "32",
                            "--output-dir",
                            str(root / "bad"),
                        ]
                    ),
                    1,
                )
            self.assertFalse((root / "bad").exists())
