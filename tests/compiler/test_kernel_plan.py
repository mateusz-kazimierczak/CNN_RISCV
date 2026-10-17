"""Authoritative kernel choices, static eligibility and compilation reuse."""

import copy
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fixtures.tflite_builder import O, Q, T, build_model

from compiler.emit_cpp import emit_cpp
from compiler.execution_plan import ExecutionPlan, validate_kernel_link
from compiler.frontend import import_bytes, import_model
from compiler.ir import ModelError
from compiler.kernel_plan import KernelPlan
from compiler.lowering import lower_graph
from compiler.quantization import prepare_graph


def softmax_graph(depth):
    shape = (1, depth)
    return import_bytes(
        build_model(
            (
                T(shape, "UINT8", q=Q((1 / 256,), (128,))),
                T(shape, q=Q((1 / 256,), (0,))),
                T(shape, q=Q((1 / 256,), (-128,))),
                T(shape, "UINT8", q=Q((1 / 256,), (0,))),
            ),
            (
                O("QUANTIZE", (0,), (1,)),
                O("SOFTMAX", (1,), (2,)),
                O("QUANTIZE", (2,), (3,)),
            ),
        )
    )


class KernelPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        cls.model = lower_graph(cls.graph)

    def test_selected_plan_roundtrip_and_static_facts(self):
        plan = self.model.kernels
        self.assertEqual(
            KernelPlan.from_json(plan.to_json(), self.graph, self.model.prepared), plan
        )
        self.assertEqual(plan.memory_contracts, self.model.contracts)
        self.assertEqual(len(plan.nodes), 64)
        n = plan.nodes[4]
        self.assertEqual(n.geometry.reduction_depth, 16)
        self.assertEqual(n.geometry.dot8_tail, 0)
        self.assertEqual(n.geometry.padding, (0, 0, 0, 0))
        self.assertTrue(n.corrected_bias_eligible)
        self.assertTrue(n.nonpositive_shifts)
        self.assertEqual(n.weight_layout, "OHWI")
        self.assertEqual(dict(n.scalar_parameters)["input_zero_point"], 1)

    def test_changed_plan_is_rejected_before_any_output(self):
        original = self.model.kernels.nodes[4]
        for selection in (
            replace(original, implementation="unimplemented"),
            replace(original, arithmetic_backend="X1"),
            replace(original, reduction_backend="xqmac8"),
            replace(original, requantization_backend="single_rounding"),
            replace(original, geometry=replace(original.geometry, reduction_depth=8)),
            replace(original, scalar_parameters=()),
            replace(original, memory=replace(original.memory, output_alignments=(8,))),
        ):
            kernels = replace(
                self.model.kernels,
                nodes=tuple(
                    selection if i == 4 else node
                    for i, node in enumerate(self.model.kernels.nodes)
                ),
            )
            changed = replace(self.model, kernels=kernels)
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "rejected"
                with self.assertRaisesRegex(ModelError, "kernel plan"):
                    emit_cpp(changed, output)
                self.assertFalse(output.exists())

    def test_unknown_saved_selection_is_rejected(self):
        data = json.loads(self.model.kernels.to_json())
        data["nodes"][4]["implementation"] = "unknown"
        with self.assertRaisesRegex(ModelError, "saved kernel plan"):
            KernelPlan.from_json(json.dumps(data), self.graph, self.model.prepared)

    def test_static_helper_limit_checked_during_lowering(self):
        lower_graph(softmax_graph(1000))
        with self.assertRaisesRegex(ModelError, "depth <= 1000"):
            lower_graph(softmax_graph(1001))

    def test_one_preparation_per_compilation_and_linked_execution_evidence(self):
        with patch(
            "compiler.compilation.prepare_graph", wraps=prepare_graph
        ) as prepare:
            model = lower_graph(self.graph)
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)
                manifest = emit_cpp(model, output)
                source = (output / "model.cc").read_text()
                self.assertIn("a0_static_shape<4>(dims_", source)
                self.assertNotIn("tflite::RuntimeShape(4, dims_", source)
                self.assertNotIn("a0_constants.p4[", source)
                self.assertIn(
                    "struct alignas(4) A0Constants",
                    (output / "constants.h").read_text(),
                )
                plan = ExecutionPlan.from_json(
                    (output / "execution_plan.json").read_text()
                )
                saved = json.loads((output / "kernel_plan.json").read_text())
                self.assertEqual(
                    plan.kernel_plan_sha256, manifest["kernel_plan_sha256"]
                )
                validate_kernel_link(plan, saved)
                bad = replace(
                    plan,
                    units=tuple(
                        replace(u, arithmetic_backend="X1") if i == 4 else u
                        for i, u in enumerate(plan.units)
                    ),
                )
                with self.assertRaisesRegex(ModelError, "selected kernel"):
                    validate_kernel_link(bad, saved)
            self.assertEqual(prepare.call_count, 1)

    def test_mutable_preparation_cannot_poison_the_compilation_cache(self):
        model = lower_graph(self.graph)
        # Even changing the context's own PreparedGraph must not alter its proof.
        model.prepared.nodes[4].integers["input_zero_point"] += 1
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.assertRaisesRegex(ModelError, "prepared parameters"),
        ):
            emit_cpp(model, Path(tmp) / "rejected")

    def test_replacing_prepared_data_or_graph_invalidates_compilation(self):
        prepared = copy.deepcopy(self.model.prepared)
        prepared.nodes[4].integers["input_zero_point"] += 1
        for model in (
            replace(self.model, prepared=prepared),
            replace(self.model, graph=replace(self.graph, description="changed")),
        ):
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ModelError):
                emit_cpp(model, Path(tmp) / "rejected")


if __name__ == "__main__":
    unittest.main()
