"""Opt-in, geometry-selected stem code generation and evidence contracts."""

import contextlib
import io
import json
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.execution_plan import ExecutionPlan, validate_kernel_link
from compiler.frontend import import_model
from compiler.ir import ModelError
from compiler.kernel_plan import (
    KernelPlan,
    STEM_UNROLL_CHOICE,
    select_kernels,
    stem_unroll_eligible,
    uses_stem_unroll,
)
from compiler.lowering import lower_graph
from compiler.quantization import prepare_graph
from compiler.frontend import import_bytes
from fixtures.tflite_builder import O, T, build_model


class StemUnrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        cls.parent = lower_graph(cls.graph, configuration="B1")
        cls.model = lower_graph(cls.graph, configuration="B1", stem_unroll=True)

    def test_opt_in_changes_only_stem_codegen_choice(self):
        a, b = self.parent, self.model
        self.assertFalse(uses_stem_unroll(a.kernels))
        self.assertTrue(uses_stem_unroll(b.kernels))
        self.assertEqual(a.memory, b.memory)
        self.assertEqual(a.prepared, b.prepared)
        changed = [
            n.node for n, old in zip(b.kernels.nodes, a.kernels.nodes) if n != old
        ]
        self.assertEqual(changed, [1])
        stem = b.kernels.nodes[1]
        self.assertEqual(
            stem,
            replace(
                a.kernels.nodes[1],
                choices=(*a.kernels.nodes[1].choices, STEM_UNROLL_CHOICE),
            ),
        )
        self.assertEqual(stem.implementation, "pinned_reference/conv_2d/int8")

    def test_eligibility_uses_geometry_not_node_number(self):
        stem = self.parent.kernels.nodes[1]
        self.assertTrue(stem_unroll_eligible(replace(stem, node=47)))
        for geometry in (
            replace(stem.geometry, weight_shape=(32, 3, 3, 4)),
            replace(stem.geometry, weight_shape=(32, 1, 1, 3)),
            replace(stem.geometry, stride=(1, 1)),
            replace(stem.geometry, dilation=(2, 2)),
            replace(stem.geometry, groups=3),
        ):
            self.assertFalse(stem_unroll_eligible(replace(stem, geometry=geometry)))
        self.assertFalse(stem_unroll_eligible(replace(stem, kind="DEPTHWISE_CONV_2D")))

    def test_roundtrip_and_invalid_codegen_choices(self):
        m = self.model
        self.assertEqual(
            KernelPlan.from_json(m.kernels.to_json(), m.graph, m.prepared), m.kernels
        )
        for mode in ("duplicate", "misplaced", "unknown"):
            data = json.loads(m.kernels.to_json())
            if mode == "duplicate":
                data["nodes"][1]["choices"].append(STEM_UNROLL_CHOICE)
            elif mode == "misplaced":
                data["nodes"][1]["choices"].remove(STEM_UNROLL_CHOICE)
                data["nodes"][2]["choices"].append(STEM_UNROLL_CHOICE)
            else:
                data["nodes"][1]["choices"][-1] = "unimplemented_unroll_policy"
            with self.subTest(mode=mode), self.assertRaises(ModelError):
                KernelPlan.from_json(json.dumps(data), m.graph, m.prepared)

    def test_reject_a0_and_conflicting_explicit_requests(self):
        with self.assertRaisesRegex(ModelError, "requires B1"):
            select_kernels(self.graph, self.model.prepared, "A0", stem_unroll=True)
        for invalid in (1, "yes"):
            with self.assertRaisesRegex(ModelError, "boolean"):
                select_kernels(
                    self.graph, self.model.prepared, "B1", stem_unroll=invalid
                )
        with self.assertRaisesRegex(ModelError, "requested stem unrolling"):
            lower_graph(self.graph, kernels=self.model.kernels, stem_unroll=False)
        graph = import_bytes(
            build_model(
                (T((1, 1, 1, 8)), T((3, 1, 1, 8), data=bytes(24)), T((1, 1, 1, 3))),
                (O("CONV_2D", (0, 1, -1), (2,)),),
            )
        )
        with self.assertRaisesRegex(ModelError, "requires a supported RGB"):
            select_kernels(graph, prepare_graph(graph), "B1", stem_unroll=True)

    def test_emission_changes_one_wrapper_and_preserves_constants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "parent"
            b = root / "stem"
            emit_cpp(self.parent, a)
            emit_cpp(self.model, b)
            for name in (
                "constants.h",
                "constants.cc",
                "memory_plan.json",
                "prepared_ir.json",
            ):
                self.assertEqual((a / name).read_bytes(), (b / name).read_bytes())
            old = (a / "model.cc").read_text().splitlines()
            new = (b / "model.cc").read_text().splitlines()
            am = json.loads((a / "source_map.json").read_text())
            bm = json.loads((b / "source_map.json").read_text())
            for x, y in zip(am["nodes"], bm["nodes"]):
                before = old[x["line"] - 1 : x["end_line"]]
                after = new[y["line"] - 1 : y["end_line"]]
                if x["node"] == 1:
                    self.assertIn("B1_STEM_UNROLL int a0_node_01", after[0])
                    self.assertEqual(before[1:], after[1:])
                else:
                    self.assertEqual(before, after)
            text = "\n".join(new)
            self.assertEqual(text.count('optimize("unroll-loops")'), 1)
            self.assertIn("!defined(__clang__) && defined(__riscv)", text)
            plan = ExecutionPlan.from_json((b / "execution_plan.json").read_text())
            validate_kernel_link(plan, json.loads((b / "kernel_plan.json").read_text()))
            self.assertIn(
                STEM_UNROLL_CHOICE, plan.units[1].memory["kernel_selection"]["choices"]
            )

    def test_cli_saved_plan_roundtrip_and_conflicting_option_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = root / "enabled.json"
            disabled = root / "disabled.json"
            saved.write_text(self.model.kernels.to_json())
            disabled.write_text(self.parent.kernels.to_json())
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "B1",
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            *args,
                            "--kernel-plan",
                            str(saved),
                            "--output-dir",
                            str(root / "roundtrip"),
                        ]
                    ),
                    0,
                )
            self.assertEqual(
                (root / "roundtrip/kernel_plan.json").read_text(), saved.read_text()
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            *args,
                            "--stem-unroll",
                            "--kernel-plan",
                            str(disabled),
                            "--output-dir",
                            str(root / "rejected"),
                        ]
                    ),
                    1,
                )
            self.assertFalse((root / "rejected").exists())
