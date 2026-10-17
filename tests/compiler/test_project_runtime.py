"""Standalone library selection, independent numerical oracle and dependency gates."""

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
from compiler.frontend import import_model
from compiler.ir import ModelError
from compiler.kernel_plan import KernelPlan, select_kernels
from compiler.lowering import lower_graph
from compiler.project_runtime import RUNTIMES, runtime_mode


class ProjectRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        cls.base = lower_graph(
            cls.graph,
            configuration="B1",
            stem_unroll=True,
            pointwise_block=4,
            depthwise_kernels=(3, 5),
        )
        cls.plans = {
            mode: select_kernels(
                cls.graph,
                cls.base.prepared,
                "B1",
                stem_unroll=True,
                pointwise_block=4,
                depthwise_kernels=(3, 5),
                runtime=mode,
            )
            for mode in RUNTIMES
        }

    def test_modes_roundtrip_and_keep_constants(self):
        for mode, p in self.plans.items():
            self.assertEqual(runtime_mode(p), mode)
            self.assertEqual(
                KernelPlan.from_json(p.to_json(), self.graph, self.base.prepared), p
            )
            m = lower_graph(self.graph, kernels=p)
            self.assertEqual(m.memory.tensors, self.base.memory.tensors)
            self.assertEqual(m.memory.parameters, self.base.memory.parameters)
        self.assertTrue(
            all(
                n.implementation.startswith(("project/", "rv64imc/"))
                for n in self.plans["standalone"].nodes
            )
        )
        self.assertEqual(
            self.plans["project-kernels"].nodes[62].implementation,
            self.base.kernels.nodes[62].implementation,
        )

    def test_unknown_forged_and_conflicting_modes(self):
        with self.assertRaises(ModelError):
            select_kernels(self.graph, self.base.prepared, "A0", runtime="standalone")
        with self.assertRaises(ModelError):
            select_kernels(self.graph, self.base.prepared, "B1", runtime="unknown")
        with self.assertRaisesRegex(ModelError, "requested runtime"):
            lower_graph(
                self.graph, kernels=self.plans["standalone"], runtime="reference"
            )
        for mode in ("mixed", "backend", "fallback"):
            data = json.loads(self.plans["standalone"].to_json())
            if mode == "mixed":
                data["nodes"][4]["choices"][-1] = "runtime_project-numerics"
            if mode == "backend":
                data["nodes"][4]["requantization_backend"] = "reference_double_rounding"
            if mode == "fallback":
                data["nodes"][1]["implementation"] = "pinned_reference/conv_2d/int8"
            with self.subTest(mode=mode), self.assertRaises(ModelError):
                KernelPlan.from_json(json.dumps(data), self.graph, self.base.prepared)

    def test_no_silent_reference_fallback(self):
        with self.assertRaisesRegex(ModelError, "depthwise selection"):
            select_kernels(self.graph, self.base.prepared, "B1", runtime="standalone")

    def test_standalone_generation_has_no_framework_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "old", Path(tmp) / "new"
            emit_cpp(self.base, a)
            manifest = emit_cpp(
                lower_graph(self.graph, kernels=self.plans["standalone"]), b
            )
            text = (b / "model.cc").read_text()
            self.assertNotIn("tflite::", text)
            self.assertNotIn("tensorflow/", text)
            self.assertNotIn("cc_softmax(", text)
            self.assertEqual(manifest["runtime"], "standalone")
            self.assertTrue(manifest["capabilities"]["standalone_target"])
            for name in ("constants.cc", "constants.h", "prepared_ir.json"):
                self.assertEqual((a / name).read_bytes(), (b / name).read_bytes())

    def test_cli_saved_runtime_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            path.write_text(self.plans["standalone"].to_json())
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "B1",
                "--kernel-plan",
                str(path),
                "--output-dir",
                str(Path(tmp) / "out"),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([*args, "--runtime", "reference"]), 1)

    def test_numerics_against_independent_pinned_oracle(self):
        upstream = ROOT / ".deps/tflite-micro"
        downloads = upstream / "tensorflow/lite/micro/tools/make/downloads"
        env = dict(os.environ)
        cxx = "g++"
        if sys.platform == "darwin":
            cxx = "/Library/Developer/CommandLineTools/usr/bin/clang++"
            env["SDKROOT"] = subprocess.check_output(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True
            ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "numeric"
            cmd = [
                cxx,
                "-std=c++17",
                "-O2",
                "-g",
                "-DTF_LITE_STATIC_MEMORY",
                "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all",
            ]
            for directory in (
                ROOT,
                ROOT / "kernels/reference",
                upstream,
                downloads / "gemmlowp",
                downloads / "ruy",
                downloads / "flatbuffers/include",
            ):
                cmd += ["-I", str(directory)]
            cmd += [
                str(ROOT / "tests/compiler/project_numerics_main.cc"),
                str(ROOT / "kernels/project/quantization.cc"),
                str(ROOT / "kernels/project/softmax.cc"),
                str(ROOT / "kernels/reference/numerics.cc"),
                str(upstream / "tensorflow/lite/kernels/internal/common.cc"),
                "-o",
                str(binary),
            ]
            r = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("200 complete Softmax cases", r.stdout)

    def test_static_operators_against_pinned_oracle(self):
        # Reuse the sanitizer/oracle compilation path with a different driver.
        # Compile directly; expected outputs always come from upstream kernels.
        upstream = ROOT / ".deps/tflite-micro"
        downloads = upstream / "tensorflow/lite/micro/tools/make/downloads"
        env = dict(os.environ)
        cxx = "g++"
        if sys.platform == "darwin":
            cxx = "/Library/Developer/CommandLineTools/usr/bin/clang++"
            env["SDKROOT"] = subprocess.check_output(
                ["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True
            ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "operators"
            cmd = [
                cxx,
                "-std=c++17",
                "-O2",
                "-g",
                "-DTF_LITE_STATIC_MEMORY",
                "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all",
            ]
            for d in (
                ROOT,
                upstream,
                downloads / "gemmlowp",
                downloads / "ruy",
                downloads / "flatbuffers/include",
            ):
                cmd += ["-I", str(d)]
            cmd += [
                str(ROOT / "tests/compiler/project_operators_main.cc"),
                str(ROOT / "kernels/project/quantization.cc"),
                str(upstream / "tensorflow/lite/kernels/internal/common.cc"),
                "-o",
                str(binary),
            ]
            r = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("65536 ADD pairs", r.stdout)

    def test_standalone_build_with_unavailable_upstream(self):
        from unittest.mock import patch
        from tools import build_a0

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "standalone"
            emit_cpp(
                lower_graph(self.graph, kernels=self.plans["standalone"]), directory
            )
            absent = Path(tmp) / "no-tflm-checkout"
            with (
                patch.object(build_a0, "UPSTREAM", absent),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                record = build_a0.build(directory, "native")
                build_a0.verify_build(directory, "native")
            self.assertFalse(absent.exists())
            self.assertEqual(record["runtime_headers_sha256"], {})
            self.assertEqual(record["external_headers_sha256"], {})
            self.assertFalse(
                any(".deps/tflite-micro" in p for p in record["dependency_sha256"])
            )

    def test_unsupported_project_geometry_rejected(self):
        from compiler.frontend import import_bytes
        from compiler.quantization import prepare_graph
        from fixtures.tflite_builder import T, O, build_model

        # A valid four-input-channel convolution cannot enter the RGB stem.
        graph = import_bytes(
            build_model(
                (T((1, 7, 7, 4)), T((4, 3, 3, 4), data=bytes(144)), T((1, 4, 4, 4))),
                (
                    O(
                        "CONV_2D",
                        (0, 1, -1),
                        (2,),
                        options={"stride_h": 2, "stride_w": 2},
                    ),
                ),
            )
        )
        with self.assertRaisesRegex(ModelError, "unsupported project convolution"):
            select_kernels(graph, prepare_graph(graph), "B1", runtime="standalone")
