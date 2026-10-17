"""Output-channel schedules, conservative fallback and saved-plan authority."""

import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.execution_plan import ExecutionPlan, validate_kernel_link
from compiler.frontend import import_model, import_bytes
from compiler.ir import ModelError
from compiler.kernel_plan import KernelPlan, select_kernels, pointwise_block_size
from compiler.lowering import lower_graph
from compiler.quantization import prepare_graph
from fixtures.tflite_builder import O, T, build_model


class PointwiseBlockingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        cls.base = lower_graph(cls.graph, configuration="B1", stem_unroll=True)

    def model(self, block):
        kernels = select_kernels(
            self.graph,
            self.base.prepared,
            "B1",
            stem_unroll=True,
            pointwise_block=block,
        )
        return lower_graph(self.graph, kernels=kernels)

    def test_uniform_schedules_change_only_pointwise_choices(self):
        for block in (2, 4):
            model = self.model(block)
            selected = [n for n in model.kernels.nodes if pointwise_block_size(n)]
            self.assertEqual(len(selected), 32)
            self.assertTrue(all(pointwise_block_size(n) == block for n in selected))
            for old, new in zip(self.base.kernels.nodes, model.kernels.nodes):
                if not pointwise_block_size(old):
                    self.assertEqual(old, new)
                else:
                    self.assertIn(f"output_channel_tile_{block}", new.choices)
                    self.assertEqual(old.geometry, new.geometry)
                    self.assertEqual(old.arithmetic_backend, new.arithmetic_backend)
                    self.assertEqual(
                        old.requantization_backend, new.requantization_backend
                    )
            self.assertEqual(model.memory.tensors, self.base.memory.tensors)
            self.assertEqual(model.memory.parameters, self.base.memory.parameters)
            self.assertEqual(model.memory.arena_bytes, 1505280)
            self.assertEqual(model.memory.rodata_bytes, self.base.memory.rodata_bytes)

    def test_nondivisible_channels_and_input_tail_keep_scalar_fallback(self):
        for k, c, request, actual in [
            (8, 3, 4, 1),
            (8, 6, 4, 1),
            (8, 6, 2, 2),
            (7, 4, 4, 0),
        ]:
            graph = import_bytes(
                build_model(
                    (
                        T((1, 1, 1, k)),
                        T((c, 1, 1, k), data=bytes(c * k)),
                        T((1, 1, 1, c)),
                    ),
                    (O("CONV_2D", (0, 1, -1), (2,)),),
                )
            )
            plan = select_kernels(
                graph, prepare_graph(graph), "B1", pointwise_block=request
            )
            self.assertEqual(pointwise_block_size(plan.nodes[0]), actual)

    def test_mixed_plan_roundtrip_uses_explicit_logical_id_overrides(self):
        plan = select_kernels(
            self.graph,
            self.base.prepared,
            "B1",
            stem_unroll=True,
            pointwise_block=2,
            pointwise_blocks={4: 1, 58: 4},
        )
        self.assertEqual(
            [pointwise_block_size(plan.nodes[n]) for n in (4, 6, 58)], [1, 2, 4]
        )
        self.assertEqual(
            KernelPlan.from_json(plan.to_json(), self.graph, self.base.prepared), plan
        )
        lower_graph(self.graph, kernels=plan)
        with self.assertRaisesRegex(ModelError, "requested pointwise block"):
            lower_graph(self.graph, kernels=plan, pointwise_block=2)

    def test_unknown_blocks_overrides_and_forged_selection_are_rejected(self):
        for block in (True, 0, 3, 8, "4"):
            with self.assertRaises(ModelError):
                select_kernels(
                    self.graph, self.base.prepared, "B1", pointwise_block=block
                )
        with self.assertRaisesRegex(ModelError, "requires B1"):
            select_kernels(self.graph, self.base.prepared, "A0", pointwise_block=2)
        for overrides in ({1: 4}, {999: 2}, {"4": 2}, {4: 8}):
            with self.assertRaises(ModelError):
                select_kernels(
                    self.graph, self.base.prepared, "B1", pointwise_blocks=overrides
                )
        data = json.loads(self.model(4).kernels.to_json())
        data["nodes"][4]["choices"][-1] = "output_channel_tile_8"
        with self.assertRaises(ModelError):
            KernelPlan.from_json(json.dumps(data), self.graph, self.base.prepared)

    def test_emission_preserves_constants_and_publishes_backend_and_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            emit_cpp(self.base, root / "base")
            for block in (2, 4):
                dest = root / str(block)
                manifest = emit_cpp(self.model(block), dest)
                for name in ("constants.h", "constants.cc", "prepared_ir.json"):
                    self.assertEqual(
                        (root / "base" / name).read_bytes(), (dest / name).read_bytes()
                    )
                source = (dest / "model.cc").read_text()
                self.assertEqual(
                    source.count("arch_project::pointwise_dot8_blocked<"), 32
                )
                self.assertEqual(source.count("B1_STEM_UNROLL int a0_node_"), 1)
                plan = ExecutionPlan.from_json(
                    (dest / "execution_plan.json").read_text()
                )
                validate_kernel_link(
                    plan, json.loads((dest / "kernel_plan.json").read_text())
                )
                self.assertEqual(plan.units[4].work["executed_products"], 19267584)
                self.assertTrue(manifest["capabilities"]["optimized_kernels"])

    def test_cli_saved_schedule_and_explicit_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = root / "plan.json"
            saved.write_text(self.model(4).kernels.to_json())
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "B1",
                "--kernel-plan",
                str(saved),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([*args, "--output-dir", str(root / "good")]), 0)
            self.assertEqual(
                (root / "good/kernel_plan.json").read_text(), saved.read_text()
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            *args,
                            "--pointwise-block",
                            "2",
                            "--output-dir",
                            str(root / "bad"),
                        ]
                    ),
                    1,
                )
            self.assertFalse((root / "bad").exists())
