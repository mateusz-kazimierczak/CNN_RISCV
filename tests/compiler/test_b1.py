"""Scalar pointwise selection, static evidence, and executable numerical tests."""

import json
import contextlib
import io
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fixtures.tflite_builder import O, Q, T, build_model
from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.execution_plan import ExecutionPlan, validate_kernel_link
from compiler.frontend import import_bytes, import_model
from compiler.ir import ModelError
from compiler.kernel_plan import B1_POINTWISE, KernelPlan, select_kernels
from compiler.lowering import lower_graph
from compiler.quantization import prepare_graph


class B1SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        cls.model = lower_graph(cls.graph, configuration="B1")

    def test_model_selects_32_pointwise_kernels_and_keeps_other_paths(self):
        model = self.model
        selected = [n for n in model.kernels.nodes if n.implementation == B1_POINTWISE]
        self.assertEqual(len(selected), 32)
        self.assertEqual(
            [model.kernels.nodes[n].geometry.reduction_depth for n in (4, 58)],
            [16, 320],
        )
        self.assertTrue(
            all(
                n.reduction_backend == "scalar_dot8" and not n.memory.scratch
                for n in selected
            )
        )
        self.assertTrue(
            model.kernels.nodes[1].implementation.startswith("pinned_reference/")
        )
        self.assertEqual(
            KernelPlan.from_json(model.kernels.to_json(), self.graph, model.prepared),
            model.kernels,
        )
        self.assertEqual(model.memory.arena_bytes, 1505280)
        for p in model.memory.parameters:
            fields = {f[0]: f for f in p.fields}
            if model.kernels.nodes[p.node].implementation == B1_POINTWISE:
                self.assertEqual(
                    fields["corrected_biases"][2],
                    len(model.prepared.nodes[p.node].adjusted_biases),
                )
            else:
                self.assertNotIn("corrected_biases", fields)

    def test_tail_and_dilation_fall_back_without_inventing_support(self):
        for k, dilation, optimized in ((8, 1, True), (7, 1, False), (8, 2, False)):
            graph = import_bytes(
                build_model(
                    (
                        T((1, 2, 2, k)),
                        T((3, 1, 1, k), data=bytes(k * 3)),
                        T(
                            (3,),
                            "INT32",
                            struct.pack("<iii", 0, 0, 0),
                            Q((0.25,), (0,)),
                        ),
                        T((1, 2, 2, 3)),
                    ),
                    (
                        O(
                            "CONV_2D",
                            (0, 1, 2),
                            (3,),
                            options={"dilation_h": dilation, "dilation_w": dilation},
                        ),
                    ),
                )
            )
            plan = select_kernels(graph, prepare_graph(graph), "B1")
            self.assertEqual(plan.nodes[0].implementation == B1_POINTWISE, optimized)

    def test_forged_b1_plan_and_configuration_rejected(self):
        model = self.model
        with self.assertRaisesRegex(ModelError, "configuration"):
            lower_graph(self.graph, kernels=model.kernels, configuration="A0")
        n = model.kernels.nodes[4]
        for changed in (
            replace(n, reduction_backend="xqmac8"),
            replace(n, choices=("unroll_16",)),
        ):
            plan = replace(
                model.kernels,
                nodes=tuple(changed if x.node == 4 else x for x in model.kernels.nodes),
            )
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "rejected"
                with self.assertRaises(ModelError):
                    emit_cpp(replace(model, kernels=plan), output)
                self.assertFalse(output.exists())

    def test_emission_preserves_selection_and_corrected_constants(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            manifest = emit_cpp(self.model, path)
            self.assertEqual(manifest["configuration"], "B1")
            self.assertEqual(manifest["stage"], 5)
            self.assertTrue(manifest["capabilities"]["optimized_kernels"])
            self.assertIn("kernels/rv64imc/pointwise.h", manifest["source_sha256"])
            source = (path / "model.cc").read_text()
            self.assertEqual(source.count("arch_project::pointwise_dot8<"), 32)
            plan = ExecutionPlan.from_json((path / "execution_plan.json").read_text())
            validate_kernel_link(
                plan, json.loads((path / "kernel_plan.json").read_text())
            )
            self.assertEqual(
                plan.units[4].work["policy"], "dense_pointwise_scalar_dot8"
            )

    def test_cli_rejects_saved_plan_configuration_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "kernel.json").write_text(self.model.kernels.to_json())
            with contextlib.redirect_stderr(io.StringIO()):
                code = main(
                    [
                        "generate",
                        str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                        "--config",
                        "A0",
                        "--kernel-plan",
                        str(path / "kernel.json"),
                        "--output-dir",
                        str(path / "rejected"),
                    ]
                )
            self.assertEqual(code, 1)
            self.assertFalse((path / "rejected").exists())


class B1NumericalTests(unittest.TestCase):
    def test_scalar_kernel_against_pinned_reference_with_sanitizers(self):
        upstream = ROOT / ".deps/tflite-micro"
        downloads = upstream / "tensorflow/lite/micro/tools/make/downloads"
        compiler = os.environ.get(
            "COMPILER_SANITIZER_CXX",
            "/Library/Developer/CommandLineTools/usr/bin/clang++"
            if sys.platform == "darwin"
            else "g++",
        )
        env = dict(os.environ)
        if sys.platform == "darwin":
            env["SDKROOT"] = subprocess.check_output(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True
            ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "pointwise"
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
            compiled = subprocess.run(
                [
                    *command,
                    str(ROOT / "tests/compiler/pointwise_main.cc"),
                    str(upstream / "tensorflow/lite/kernels/internal/common.cc"),
                    "-o",
                    str(binary),
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(
                [str(binary)], check=True, capture_output=True, text=True
            )
            self.assertIn("480 kernel cases", result.stdout)
