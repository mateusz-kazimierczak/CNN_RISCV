"""Spatial tiles preserve numerical, storage, provenance and CLI contracts."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.execution_plan import ExecutionPlan, validate_kernel_link
from compiler.frontend import import_model, import_bytes
from compiler.ir import ModelError
from compiler.kernel_plan import (
    KernelPlan,
    select_kernels,
    pointwise_block_size,
    pointwise_pixels,
)
from compiler.lowering import lower_graph
from compiler.quantization import prepare_graph
from compiler.requantization import requantization_overrides
from fixtures.tflite_builder import T, O, build_model

ROOT = Path(__file__).resolve().parents[2]


class SpatialPointwiseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        # Reconstruct using typed facts, not a captured binary or a label.
        cls.base = lower_graph(
            cls.graph,
            configuration="B1",
            runtime="standalone",
            stem_unroll=True,
            pointwise_block=4,
            depthwise_kernels=(3, 5),
            requantization="nonpositive",
            requantization_overrides={
                n: "inline-nonpositive"
                for n in (
                    1,
                    2,
                    3,
                    4,
                    5,
                    6,
                    7,
                    8,
                    9,
                    11,
                    12,
                    14,
                    15,
                    18,
                    19,
                    20,
                    21,
                    22,
                    25,
                    26,
                    29,
                    41,
                    44,
                    48,
                    52,
                )
            },
        )

    def plan(self, block=4, pixels=2, tiles=None):
        return select_kernels(
            self.graph,
            self.base.prepared,
            "B1",
            runtime="standalone",
            stem_unroll=True,
            pointwise_block=block,
            pointwise_pixels=pixels,
            pointwise_tiles=tiles,
            depthwise_kernels=(3, 5),
            requantization="nonpositive",
            requantization_overrides=requantization_overrides(self.base.kernels),
        )

    def test_only_pointwise_changes_and_memory_payloads_stay_equal(self):
        for block in (2, 4):
            plan = self.plan(block)
            self.assertEqual(
                KernelPlan.from_json(plan.to_json(), self.graph, self.base.prepared),
                plan,
            )
            model = lower_graph(
                self.graph, kernels=plan, pointwise_pixels=2, pointwise_block=block
            )
            self.assertEqual(model.memory.tensors, self.base.memory.tensors)
            self.assertEqual(model.memory.parameters, self.base.memory.parameters)
            self.assertEqual(model.memory.arena_bytes, self.base.memory.arena_bytes)
            self.assertEqual(model.memory.rodata_bytes, self.base.memory.rodata_bytes)
            self.assertEqual(sum(pointwise_pixels(n) == 2 for n in plan.nodes), 32)
            for old, new in zip(self.base.kernels.nodes, plan.nodes):
                if not pointwise_block_size(old):
                    self.assertEqual(old, new)
                else:
                    self.assertEqual(
                        new.requantization_backend, old.requantization_backend
                    )
                    self.assertEqual(new.geometry, old.geometry)
                    self.assertIn("weights_shared_across_pixels", new.choices)
                    self.assertEqual(new.reduction_backend, "scalar_dot8_spatial2")
            self.assertIn("odd_pixel_tail_single_pixel", plan.nodes[58].choices)

    def test_mixed_schedules_roundtrip_and_conflicts(self):
        tiles = {4: (2, 2), 58: (2, 4)}
        plan = self.plan(pixels=1, tiles=tiles)
        self.assertEqual(
            [pointwise_pixels(plan.nodes[n]) for n in (4, 6, 58)], [2, 1, 2]
        )
        self.assertEqual(
            KernelPlan.from_json(plan.to_json(), self.graph, self.base.prepared), plan
        )
        lower_graph(self.graph, kernels=plan, pointwise_tiles=tiles)
        for kwargs in (
            {"pointwise_pixels": 2},
            {"pointwise_block": 4},
            {"pointwise_tiles": {}},
        ):
            with self.assertRaisesRegex(ModelError, "requested pointwise"):
                lower_graph(self.graph, kernels=plan, **kwargs)

    def test_invalid_and_forged_schedules(self):
        for pixels in (True, 0, 3, "2"):
            with self.assertRaises(ModelError):
                self.plan(pixels=pixels)
        for tiles in (
            {4: (2, 1)},
            {4: (4, 4)},
            {4: [2, 4]},
            {1: (2, 4)},
            {999: (2, 4)},
            {True: (2, 4)},
        ):
            with self.subTest(tiles=tiles), self.assertRaises(ModelError):
                self.plan(tiles=tiles)
        with self.assertRaises(ModelError):
            select_kernels(
                self.graph,
                self.base.prepared,
                "A0",
                pointwise_pixels=2,
                pointwise_block=4,
            )
        plan = self.plan()
        for field, value in (
            ("reduction_backend", "scalar_dot8"),
            ("choices", ["spatial_pixel_tile_4"]),
        ):
            data = json.loads(plan.to_json())
            data["nodes"][4][field] = value
            with self.assertRaises(ModelError):
                KernelPlan.from_json(json.dumps(data), self.graph, self.base.prepared)

    def test_unsupported_geometry_fallback_and_single_pixel(self):
        for k, c, expected in ((8, 4, 2), (8, 3, 1), (7, 4, 0)):
            graph = import_bytes(
                build_model(
                    (
                        T((1, 1, 1, k)),
                        T((c, 1, 1, k), data=bytes(k * c)),
                        T((1, 1, 1, c)),
                    ),
                    (O("CONV_2D", (0, 1, -1), (2,)),),
                )
            )
            plan = select_kernels(
                graph, prepare_graph(graph), "B1", pointwise_block=4, pointwise_pixels=2
            )
            self.assertEqual(pointwise_pixels(plan.nodes[0]), expected)
            if expected == 2:
                self.assertIn("odd_pixel_tail_single_pixel", plan.nodes[0].choices)

    def test_emission_execution_work_and_saved_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            emit_cpp(self.base, root / "base")
            for block in (2, 4):
                dest = root / str(block)
                plan = self.plan(block)
                emit_cpp(lower_graph(self.graph, kernels=plan), dest)
                for name in ("constants.h", "constants.cc", "prepared_ir.json"):
                    self.assertEqual(
                        (root / "base" / name).read_bytes(), (dest / name).read_bytes()
                    )
                self.assertEqual(
                    (dest / "model.cc")
                    .read_text()
                    .count("arch_project::pointwise_dot8_spatial2<"),
                    32,
                )
                ep = ExecutionPlan.from_json((dest / "execution_plan.json").read_text())
                validate_kernel_link(
                    ep, json.loads((dest / "kernel_plan.json").read_text())
                )
                self.assertEqual(ep.units[4].work["executed_products"], 19267584)
                self.assertEqual(
                    ep.units[4].work["policy"], "dense_pointwise_scalar_dot8_spatial2"
                )
            args = [
                "generate",
                str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                "--config",
                "B1",
                "--kernel-plan",
                str(root / "4/kernel_plan.json"),
                "--output-dir",
                str(root / "saved"),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main([*args, "--pointwise-pixels", "2", "--pointwise-block", "4"]),
                    0,
                )
            for extra in (
                ["--pointwise-pixels", "1"],
                ["--pointwise-tile", "4:2:2"],
                ["--pointwise-tile", "4:2:4", "--pointwise-tile", "4:2:4"],
                ["--pointwise-tile", "bad"],
            ):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main([*args, *extra]), 1)

    def test_all_policies_against_pinned_kernel_under_sanitizers(self):
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
            binary = Path(tmp) / "spatial"
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
                str(ROOT / "tests/compiler/spatial_pointwise_main.cc"),
                str(ROOT / "kernels/project/quantization.cc"),
                str(upstream / "tensorflow/lite/kernels/internal/common.cc"),
                "-o",
                str(binary),
            ]
            r = subprocess.run(cmd, env=env, text=True, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("tails and batches: PASS", r.stdout)
            print(r.stdout.strip(), flush=True)
