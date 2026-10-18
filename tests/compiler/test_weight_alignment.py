"""Packed-weight alignment contracts, storage, emission and saved-plan gates."""

import contextlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.frontend import import_bytes
from compiler.ir import ModelError
from compiler.kernel_plan import KernelPlan, select_kernels, validate_pointwise_request
from compiler.lowering import lower_graph
from compiler.memory_plan import MemoryPlan, plan_memory, validate_memory_plan
from compiler.quantization import prepare_graph
from fixtures.tflite_builder import O, Q, T, build_model
import test_xqmac8


class WeightAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_xqmac8.Xqmac8Tests.setUpClass()
        cls.graph, cls.prepared = (
            test_xqmac8.Xqmac8Tests.graph,
            test_xqmac8.Xqmac8Tests.prepared,
        )
        cls.original = lower_graph(
            cls.graph, cls.prepared, kernels=test_xqmac8.Xqmac8Tests.x1
        )
        cls.aligned = lower_graph(
            cls.graph,
            cls.prepared,
            configuration="X1",
            xqmac8_weight_alignment=8,
            **test_xqmac8.Xqmac8Tests.options,
        )

    def test_alignment_proof_preserves_all_offsets_payloads_and_workspace(self):
        old, new = self.original, self.aligned
        self.assertEqual(new.memory.rodata_alignment, 8)
        self.assertEqual(new.memory.rodata_bytes, old.memory.rodata_bytes)
        self.assertEqual(new.memory.arena_bytes, old.memory.arena_bytes)
        self.assertEqual(new.memory.parameters, old.memory.parameters)
        selected = 0
        for previous, current in zip(old.kernels.nodes, new.kernels.nodes):
            if current.reduction_backend.startswith("xqmac8"):
                selected += 1
                operand = next(m for m in current.memory.inputs if m.role == "weights")
                self.assertEqual(operand.alignment, 8)
                tid = self.graph.nodes[current.node].input("weights")
                self.assertEqual(new.memory.tensors[tid].alignment, 8)
                self.assertEqual(new.memory.tensors[tid].offset % 8, 0)
                self.assertEqual(current.geometry.input_shape[-1] % 8, 0)
            else:
                self.assertEqual(previous, current)
        self.assertEqual(selected, 32)
        for a, b in zip(old.memory.tensors, new.memory.tensors):
            self.assertEqual(
                (a.offset, a.size_bytes, a.section), (b.offset, b.size_bytes, b.section)
            )

    def test_emission_uses_real_alignment_and_keeps_constants_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            emit_cpp(self.original, root / "old")
            emit_cpp(self.aligned, root / "new")
            self.assertEqual(
                (root / "old/constants.cc").read_bytes(),
                (root / "new/constants.cc").read_bytes(),
            )
            self.assertIn(
                "struct alignas(8) A0Constants", (root / "new/constants.h").read_text()
            )
            self.assertEqual(
                (root / "new/model.cc").read_text().count("Qmac8SpatialBlock<8, 8>"), 32
            )
            saved = KernelPlan.from_json(
                (root / "new/kernel_plan.json").read_text(), self.graph, self.prepared
            )
            self.assertEqual(saved, self.aligned.kernels)
            restored = MemoryPlan.from_json(
                (root / "new/memory_plan.json").read_text(),
                self.graph,
                self.prepared,
                saved.memory_contracts,
            )
            self.assertEqual(restored, self.aligned.memory)

    def test_forged_proofs_mixed_plans_and_unsupported_requests_are_rejected(self):
        with self.assertRaises(ModelError):
            validate_memory_plan(
                replace(self.aligned.memory, rodata_alignment=4),
                self.graph,
                self.prepared,
                self.aligned.contracts,
            )
        with self.assertRaises(ModelError):
            lower_graph(
                self.graph,
                self.prepared,
                self.original.memory,
                kernels=self.aligned.kernels,
            )
        with self.assertRaises(ModelError):
            lower_graph(
                self.graph, kernels=self.aligned.kernels, xqmac8_weight_alignment=4
            )
        for config, value in (("B1", 8), ("A0", 8), ("X1", 16), ("X1", True)):
            with (
                self.subTest(config=config, value=value),
                self.assertRaises(ModelError),
            ):
                select_kernels(
                    self.graph, self.prepared, config, xqmac8_weight_alignment=value
                )
        validate_pointwise_request(
            self.aligned.kernels, self.graph, self.prepared, block=2, pixels=2
        )

    def test_saved_cli_roundtrip_and_explicit_alignment_conflict(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            root = Path(temporary)
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "X1",
            ]
            self.assertEqual(
                main(
                    [
                        *args,
                        "--xqmac8-weight-alignment",
                        "8",
                        "--output-dir",
                        str(root / "first"),
                    ]
                ),
                0,
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
                            "--xqmac8-weight-alignment",
                            "4",
                            "--output-dir",
                            str(root / "rejected"),
                        ]
                    ),
                    1,
                )
            self.assertFalse((root / "rejected").exists())

    def test_constants_extent_includes_tail_padding_for_stronger_object_alignment(self):
        graph = import_bytes(
            build_model(
                (
                    T((1, 1, 1, 8)),
                    T((1, 1, 1, 8), data=bytes(range(8))),
                    T((1,), "INT32", struct.pack("<i", 0), Q((0.25,), (0,))),
                    T((1, 1, 1, 1)),
                ),
                (O("CONV_2D", (0, 1, 2), (3,)),),
            )
        )
        prepared = prepare_graph(graph)
        kernels = select_kernels(graph, prepared, "X1", xqmac8_weight_alignment=8)
        memory = plan_memory(graph, prepared, kernels.memory_contracts)
        end = max(
            [t.offset + t.size_bytes for t in memory.tensors if t.section == ".rodata"]
            + [p.offset + p.size_bytes for p in memory.parameters if p.size_bytes]
        )
        self.assertEqual(memory.rodata_bytes, (end + 7) // 8 * 8)
        self.assertEqual(memory.rodata_alignment, 8)
        self.assertEqual(end % 8, 4)


if __name__ == "__main__":
    unittest.main()
