"""Static depthwise selection, evidence, fallback, and exact numerical tests."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.execution_plan import ExecutionPlan, validate_kernel_link
from compiler.frontend import import_model
from compiler.ir import ModelError
from compiler.kernel_plan import (
    KernelPlan,
    depthwise_eligible,
    depthwise_filter_size,
    selected_depthwise_kernels,
    select_kernels,
)
from compiler.lowering import lower_graph


class DepthwiseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        cls.parent = lower_graph(
            cls.graph, configuration="B1", stem_unroll=True, pointwise_block=4
        )
        cls.model = lower_graph(
            cls.graph,
            configuration="B1",
            stem_unroll=True,
            pointwise_block=4,
            depthwise_kernels=(3, 5),
        )

    def test_independent_flags_and_exact_scope(self):
        for sizes, count in (((3,), 7), ((5,), 9), ((3, 5), 16)):
            plan = select_kernels(
                self.graph,
                self.model.prepared,
                "B1",
                stem_unroll=True,
                pointwise_block=4,
                depthwise_kernels=sizes,
            )
            changed = [
                n for n, old in zip(plan.nodes, self.parent.kernels.nodes) if n != old
            ]
            self.assertEqual(len(changed), count)
            self.assertTrue(all(depthwise_filter_size(n) in sizes for n in changed))
            self.assertTrue(all(not n.memory.scratch for n in changed))
            self.assertEqual(
                KernelPlan.from_json(plan.to_json(), self.graph, self.model.prepared),
                plan,
            )
        self.assertEqual(self.model.prepared, self.parent.prepared)
        self.assertEqual(self.model.memory.tensors, self.parent.memory.tensors)
        self.assertEqual(self.model.memory.parameters, self.parent.memory.parameters)
        self.assertEqual(selected_depthwise_kernels(self.model.kernels), (3, 5))

    def test_geometry_and_reference_fallback(self):
        node = self.model.kernels.nodes[8]
        self.assertTrue(depthwise_eligible(replace(node, node=47), 3))
        for g in (
            replace(node.geometry, dilation=(2, 1)),
            replace(node.geometry, depth_multiplier=2),
            replace(node.geometry, stride=(3, 1)),
            replace(node.geometry, weight_shape=(1, 3, 5, 144)),
            replace(node.geometry, output_shape=(1, 56, 56, 288)),
        ):
            self.assertFalse(depthwise_eligible(replace(node, geometry=g), 3))
        self.assertFalse(depthwise_eligible(replace(node, kind="CONV_2D"), 3))
        self.assertFalse(
            any(depthwise_filter_size(n) for n in self.parent.kernels.nodes)
        )
        # Exercise the selector, not just its predicate, on valid dilated and
        # depth-multiplied tiny graphs, using the existing FlatBuffer fixture.
        from compiler.frontend import import_bytes
        from compiler.quantization import prepare_graph
        from fixtures.tflite_builder import O, Q, T, build_model

        for dilation, multiplier in ((2, 1), (1, 2)):
            c = 2 * multiplier
            graph = import_bytes(
                build_model(
                    (
                        T((1, 5, 5, 2)),
                        T((1, 3, 3, c), data=bytes(9 * c), q=Q(axis=3)),
                        T((1, 5, 5, c)),
                    ),
                    (
                        O(
                            "DEPTHWISE_CONV_2D",
                            (0, 1, -1),
                            (2,),
                            options={
                                "dilation_h": dilation,
                                "dilation_w": dilation,
                                "depth_multiplier": multiplier,
                            },
                        ),
                    ),
                )
            )
            plan = select_kernels(
                graph, prepare_graph(graph), "B1", depthwise_kernels=(3, 5)
            )
            self.assertTrue(
                plan.nodes[0].implementation.startswith("pinned_reference/")
            )

    def test_forged_plans_and_invalid_options_rejected(self):
        for value in ((3, 3), (True,), (7,), [3], "3"):
            with self.subTest(value=value), self.assertRaises(ModelError):
                select_kernels(
                    self.graph, self.model.prepared, "B1", depthwise_kernels=value
                )
        with self.assertRaisesRegex(ModelError, "require B1"):
            select_kernels(
                self.graph, self.model.prepared, "A0", depthwise_kernels=(3,)
            )
        for mode in ("unknown", "misplaced", "omitted", "forged_stride"):
            data = json.loads(self.model.kernels.to_json())
            if mode == "unknown":
                data["nodes"][8]["choices"].append("xqmac")
            if mode == "misplaced":
                data["nodes"][4]["implementation"] = data["nodes"][8]["implementation"]
            if mode == "omitted":
                data["nodes"][8] = json.loads(self.parent.kernels.to_json())["nodes"][8]
            if mode == "forged_stride":
                data["nodes"][8]["geometry"]["stride"] = [2, 2]
            with self.subTest(mode=mode), self.assertRaises(ModelError):
                KernelPlan.from_json(json.dumps(data), self.graph, self.model.prepared)
        with self.assertRaisesRegex(ModelError, "requested depthwise"):
            lower_graph(self.graph, kernels=self.model.kernels, depthwise_kernels=(3,))
        self.assertEqual(
            lower_graph(
                self.graph, kernels=self.model.kernels, pointwise_block=4
            ).kernels,
            self.model.kernels,
        )

    def test_codegen_constants_and_work_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "parent", Path(tmp) / "depthwise"
            emit_cpp(self.parent, a)
            manifest = emit_cpp(self.model, b)
            for name in ("constants.h", "constants.cc", "prepared_ir.json"):
                self.assertEqual((a / name).read_bytes(), (b / name).read_bytes())
            text = (b / "model.cc").read_text()
            self.assertEqual(text.count("arch_project::depthwise_fixed<"), 16)
            self.assertIn("kernels/rv64imc/depthwise.h", manifest["source_sha256"])
            self.assertEqual(manifest["stage"], 6)
            plan = ExecutionPlan.from_json((b / "execution_plan.json").read_text())
            old = ExecutionPlan.from_json((a / "execution_plan.json").read_text())
            validate_kernel_link(plan, json.loads((b / "kernel_plan.json").read_text()))
            for n, o in zip(plan.units, old.units):
                self.assertEqual(
                    n.work["executed_products"], o.work["executed_products"]
                )
            self.assertEqual(
                plan.units[8].work["policy"], "depthwise_static_valid_taps"
            )

    def test_cli_roundtrip_and_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = root / "plan.json"
            saved.write_text(self.model.kernels.to_json())
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "B1",
                "--kernel-plan",
                str(saved),
                "--output-dir",
                str(root / "out"),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
                self.assertEqual(main([*args, "--depthwise-kernels", "5", "3"]), 0)
            self.assertEqual(
                (root / "out/kernel_plan.json").read_text(), saved.read_text()
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([*args, "--depthwise-kernels", "3"]), 1)

    def test_reference_numerics_under_sanitizers(self):
        upstream = ROOT / ".deps/tflite-micro"
        downloads = upstream / "tensorflow/lite/micro/tools/make/downloads"
        env = dict(os.environ)
        compiler = "g++"
        if sys.platform == "darwin":
            compiler = "/Library/Developer/CommandLineTools/usr/bin/clang++"
            env["SDKROOT"] = subprocess.check_output(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True
            ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "depthwise"
            command = [
                compiler,
                "-std=c++17",
                "-O2",
                "-g",
                "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all",
                "-DTF_LITE_STATIC_MEMORY",
            ]
            for directory in (
                ROOT,
                upstream,
                downloads / "gemmlowp",
                downloads / "ruy",
                downloads / "flatbuffers/include",
            ):
                command += ["-I", str(directory)]
            result = subprocess.run(
                [
                    *command,
                    str(ROOT / "tests/compiler/depthwise_main.cc"),
                    str(upstream / "tensorflow/lite/kernels/internal/common.cc"),
                    "-o",
                    str(binary),
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("320 kernel cases", result.stdout)
