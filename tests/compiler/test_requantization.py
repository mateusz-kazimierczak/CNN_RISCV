"""Proven software scaling selection, serialization and generated call policies."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.frontend import import_model
from compiler.ir import ModelError
from compiler.kernel_plan import KernelPlan, select_kernels, validate_kernel_plan
from compiler.lowering import lower_graph
from compiler.requantization import (
    BACKENDS,
    apply_requantization,
    requantization_mode,
    requantization_overrides,
)

ROOT = Path(__file__).resolve().parents[2]


class RequantizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        cls.base = lower_graph(
            cls.graph,
            configuration="B1",
            runtime="standalone",
            pointwise_block=4,
            depthwise_kernels=(3, 5),
            stem_unroll=True,
        )

    def plan(self, mode, **kwargs):
        return select_kernels(
            self.graph,
            self.base.prepared,
            "B1",
            runtime="standalone",
            pointwise_block=4,
            depthwise_kernels=(3, 5),
            stem_unroll=True,
            requantization=mode,
            **kwargs,
        )

    def test_proofs_roundtrip_and_unchanged_memory(self):
        for mode, backend in BACKENDS.items():
            with self.subTest(mode=mode):
                plan = self.plan(mode)
                self.assertEqual(requantization_mode(plan), mode)
                self.assertEqual(
                    KernelPlan.from_json(
                        plan.to_json(), self.graph, self.base.prepared
                    ),
                    plan,
                )
                specialized = [
                    n for n in plan.nodes if n.requantization_backend == backend
                ]
                self.assertEqual(len(specialized), 49)
                self.assertTrue(all(n.nonpositive_shifts for n in specialized))
                lowered = lower_graph(self.graph, kernels=plan, pointwise_block=4)
                self.assertEqual(lowered.memory, self.base.memory)
                for before, after in zip(self.base.kernels.nodes, plan.nodes):
                    self.assertEqual(before.memory, after.memory)
                    self.assertEqual(before.reduction_backend, after.reduction_backend)

    def test_invalid_modes_and_conflicts(self):
        for configuration, runtime, mode in (
            ("A0", "reference", "nonpositive"),
            ("B1", "reference", "nonpositive"),
            ("B1", "standalone", "unknown"),
        ):
            with self.assertRaises(ModelError):
                select_kernels(
                    self.graph,
                    self.base.prepared,
                    configuration,
                    runtime=runtime,
                    requantization=mode,
                )
        with self.assertRaisesRegex(ModelError, "requested requantization"):
            lower_graph(
                self.graph, kernels=self.plan("nonpositive"), requantization="generic"
            )

    def test_per_node_policies_roundtrip_and_reject_invalid_targets(self):
        overrides = {
            1: "inline-nonpositive",
            4: "inline-nonpositive",
            8: "inline-nonpositive",
        }
        plan = self.plan("nonpositive", requantization_overrides=overrides)
        self.assertEqual(requantization_overrides(plan), overrides)
        self.assertEqual(
            KernelPlan.from_json(plan.to_json(), self.graph, self.base.prepared), plan
        )
        lower_graph(
            self.graph,
            kernels=plan,
            pointwise_block=4,
            requantization_overrides=overrides,
        )
        for node in (1, 4, 8):
            self.assertEqual(
                plan.nodes[node].requantization_backend, BACKENDS["inline-nonpositive"]
            )
        self.assertEqual(plan.nodes[58].requantization_backend, BACKENDS["nonpositive"])
        for invalid in (
            {10: "inline-nonpositive"},
            {-1: "inline-nonpositive"},
            {4: "unknown"},
            {True: "inline-nonpositive"},
        ):
            with self.subTest(overrides=invalid), self.assertRaises(ModelError):
                self.plan("nonpositive", requantization_overrides=invalid)
        with self.assertRaisesRegex(ModelError, "requested requantization overrides"):
            lower_graph(self.graph, kernels=plan, requantization_overrides={})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            emit_cpp(lower_graph(self.graph, kernels=plan), path / "model")
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "B1",
                "--kernel-plan",
                str(path / "model/kernel_plan.json"),
                "--output-dir",
                str(path / "saved"),
                "--requantization",
                "nonpositive",
                "--requantization-inline-nodes",
                "1",
                "4",
                "8",
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
            for nodes in (["1", "4"], ["1", "1"]):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main([*args[:-3], *nodes]), 1)

    def test_forged_backend_proof_and_mixed_modes(self):
        for field, value in (
            ("requantization_backend", "project_double_rounding"),
            ("nonpositive_shifts", False),
            ("choices", ["requantization_inline-nonpositive"]),
        ):
            data = json.loads(self.plan("nonpositive").to_json())
            data["nodes"][4][field] = value
            with self.subTest(field=field), self.assertRaises(ModelError):
                KernelPlan.from_json(json.dumps(data), self.graph, self.base.prepared)
        plan = self.plan("nonpositive")
        changed = replace(
            plan.nodes[4], requantization_backend="reference_double_rounding"
        )
        with self.assertRaises(ModelError):
            validate_kernel_plan(
                replace(plan, nodes=(*plan.nodes[:4], changed, *plan.nodes[5:])),
                self.graph,
                self.base.prepared,
            )

    def test_positive_shifts_keep_generic_and_bad_proofs_fail(self):
        nodes = list(self.base.kernels.nodes)
        nodes[4] = replace(nodes[4], nonpositive_shifts=False)
        result = apply_requantization(nodes, self.base.prepared, "nonpositive")
        self.assertEqual(result[4].requantization_backend, "project_double_rounding")
        prepared = self.base.prepared
        params = list(prepared.nodes)
        params[4] = replace(
            params[4],
            integers={
                **params[4].integers,
                "shifts": [1] * len(params[4].integers["shifts"]),
            },
        )
        with self.assertRaisesRegex(ModelError, "invalid nonpositive scaling proof"):
            apply_requantization(
                self.base.kernels.nodes,
                replace(prepared, nodes=tuple(params)),
                "nonpositive",
            )

    def test_emission_and_cli_saved_policy_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for mode, policy in (
                ("nonpositive", "NonpositiveRequantization"),
                ("inline-nonpositive", "InlineNonpositiveRequantization"),
            ):
                path = directory / mode
                plan = self.plan(mode)
                emit_cpp(lower_graph(self.graph, kernels=plan), path)
                source = (path / "model.cc").read_text()
                self.assertEqual(
                    source.count(
                        f"/* Requantization */ arch_project::numeric::{policy}"
                    ),
                    49,
                )
                args = [
                    "generate",
                    str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                    "--config",
                    "B1",
                    "--kernel-plan",
                    str(path / "kernel_plan.json"),
                    "--output-dir",
                    str(directory / "saved"),
                    "--pointwise-block",
                    "4",
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main([*args, "--requantization", mode]), 0)
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main([*args, "--requantization", "generic"]), 1)
