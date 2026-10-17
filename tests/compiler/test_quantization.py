"""Exact prepared-parameter parity and standalone numeric differential tests."""

from __future__ import annotations

import ctypes
import json
import random
import struct
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fixtures.tflite_builder import Q, build_model
from test_frontend import (
    add_fixture,
    conv_fixture,
    depthwise_fixture,
    fc_fixture,
    pool_fixture,
    quantize_fixture,
    reshape_fixture,
    softmax_fixture,
)

from compiler.frontend import import_bytes, import_model
from compiler.ir import ModelError
from compiler.oracle import verify_golden
from compiler.quantization import (
    I32_MAX,
    I32_MIN,
    PreparedGraph,
    add_scalar,
    adjusted_bias,
    average_pool,
    clamp,
    compare_prepared,
    dot,
    f32,
    high_mul,
    prepare_graph,
    quantize_multiplier,
    requantize,
    rounding_divide,
)
from tools.prepare_compiler import NATIVE, capture_parameters, verify_build

P32 = ctypes.POINTER(ctypes.c_int32)
P8 = ctypes.POINTER(ctypes.c_int8)
PU8 = ctypes.POINTER(ctypes.c_uint8)


def signed(data):
    return [x if x < 128 else x - 256 for x in data]


def array8(values):
    return (ctypes.c_int8 * len(values))(*values)


def add_params(p):
    keys = (
        "input1_offset",
        "input2_offset",
        "output_offset",
        "input1_multiplier",
        "input2_multiplier",
        "output_multiplier",
        "input1_shift",
        "input2_shift",
        "output_shift",
        "left_shift",
        "output_activation_min",
        "output_activation_max",
    )
    return (ctypes.c_int32 * len(keys))(*(p[k] for k in keys))


class QuantizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = json.loads((NATIVE / "build.json").read_text())
        verify_build(cls.record)
        cls.native = ctypes.CDLL(str(ROOT / cls.record["shared"]))
        signatures = {
            "cc_requantize": [ctypes.c_int32, ctypes.c_int32, ctypes.c_int, P32],
            "cc_softmax": [
                P8,
                ctypes.c_int,
                ctypes.c_int32,
                ctypes.c_int,
                ctypes.c_int,
                P8,
                P32,
                ctypes.POINTER(ctypes.c_int),
            ],
            "cc_add": [ctypes.c_int, ctypes.c_int, P32, P32],
            "cc_pool": [P8, ctypes.c_int, ctypes.c_int, ctypes.c_int, P32],
            "cc_dot": [P8, P8, ctypes.c_int, ctypes.c_int, ctypes.c_int32, P32],
            "cc_boundary": [PU8, ctypes.c_int, ctypes.c_bool, PU8],
            "cc_conv_border": [P8, P8, ctypes.c_int, P32, P8],
        }
        for name, types in signatures.items():
            getattr(cls.native, name).argtypes = types
            getattr(cls.native, name).restype = ctypes.c_int
        cls.graph = import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        cls.prepared = prepare_graph(cls.graph)
        cls.capture = Path(
            json.loads((ROOT / "build/compiler/oracle/latest.json").read_text())[
                "capture"
            ]
        )
        cls.manifest = verify_golden(
            cls.capture, ROOT / "tests/compiler/fixtures/oracle-golden.json"
        )

    def test_actual_prepare_all_nodes_elementwise(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = capture_parameters(
                ROOT / "models/efficientnet-lite0-int8.tflite",
                Path(directory),
                self.record,
            )
        self.assertEqual(compare_prepared(self.prepared, rows), 42598)

    def test_prepared_ir_deterministic_and_keeps_static_runtime_distinction(self):
        text = self.prepared.to_json()
        self.assertEqual(text, prepare_graph(self.graph).to_json())
        ir = json.loads(text)
        self.assertEqual(ir["graph_ir_sha256"], self.graph.sha256)
        self.assertFalse(ir["capabilities"]["memory_plan"])
        self.assertFalse(ir["capabilities"]["inference_codegen"])
        self.assertEqual(len(ir["nodes"]), 64)
        self.assertIn(
            "softmax row max/sum/reciprocal/exponent",
            ir["arithmetic"]["runtime_parameters"],
        )
        self.assertEqual(
            PreparedGraph.from_json(text, self.graph).sha256, self.prepared.sha256
        )
        ir["nodes"][1]["integers"]["multipliers"][0] += 1
        with self.assertRaisesRegex(ModelError, "prepared IR differs"):
            PreparedGraph.from_json(json.dumps(ir), self.graph)

    def test_parity_rejects_missing_extra_and_changed_integer(self):
        rows = [
            {"node": n.node, "kind": n.kind, "integers": dict(n.integers)}
            for n in self.prepared.nodes
        ]
        for key, value in (("requantize_output_multiplier", 1), ("unexpected", 1)):
            changed = json.loads(json.dumps(rows))
            changed[0]["integers"][key] = value
            with self.assertRaisesRegex(ModelError, "node 0"):
                compare_prepared(self.prepared, changed)
        with self.assertRaises(ModelError):
            compare_prepared(self.prepared, rows[:-1])
        changed = json.loads(json.dumps(rows))
        changed[1]["integers"]["shifts"][0] += 1
        with self.assertRaisesRegex(ModelError, "node 1"):
            compare_prepared(self.prepared, changed)

    def test_tiny_models_actual_prepare_all_kinds_and_absent_bias(self):
        fixtures = []
        for factory in (
            conv_fixture,
            depthwise_fixture,
            fc_fixture,
            add_fixture,
            pool_fixture,
            quantize_fixture,
            reshape_fixture,
            softmax_fixture,
        ):
            tensors, nodes = factory()
            if factory == conv_fixture:
                tensors = (
                    *tensors[:2],
                    replace(tensors[2], data=struct.pack("<ii", -17, 31)),
                    tensors[3],
                )
            fixtures.append((tensors, nodes))
            if factory in (conv_fixture, depthwise_fixture, fc_fixture):
                fixtures.append((tensors, (replace(nodes[0], inputs=(0, 1)),)))
        for tensors, nodes in fixtures:
            with (
                self.subTest(kind=nodes[0].kind, inputs=nodes[0].inputs),
                tempfile.TemporaryDirectory() as directory,
            ):
                data = build_model(
                    tensors, nodes, inputs=(0, 1) if nodes[0].kind == "ADD" else (0,)
                )
                model = Path(directory) / "model.tflite"
                model.write_bytes(data)
                capture_parameters(model, Path(directory) / "prepared", self.record)

    def test_fused_clamps_actual_prepare(self):
        for activation in ("NONE", "RELU", "RELU6", "RELU_N1_TO_1"):
            for factory in (
                conv_fixture,
                depthwise_fixture,
                fc_fixture,
                add_fixture,
                pool_fixture,
            ):
                tensors, (node,) = factory()
                if factory == conv_fixture:
                    tensors = (
                        *tensors[:2],
                        replace(tensors[2], data=bytes(8)),
                        tensors[3],
                    )
                with (
                    self.subTest(kind=node.kind, activation=activation),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    model = Path(directory) / "fixture.tflite"
                    model.write_bytes(
                        build_model(
                            tensors,
                            (replace(node, options={"fused_activation": activation}),),
                            inputs=(0, 1) if node.kind == "ADD" else (0,),
                        )
                    )
                    capture_parameters(model, Path(directory) / "capture", self.record)

    def test_fc_float_product_rounding_is_distinct(self):
        # Values where binary32 multiplication changes a prepared integer.
        tensors, nodes = fc_fixture()
        tensors = (
            replace(tensors[0], q=Q((0.1234567,), (-17,))),
            replace(tensors[1], q=Q((0.2345678,), (0,))),
            replace(tensors[2], q=Q((f32(f32(0.1234567) * f32(0.2345678)),), (0,))),
            replace(tensors[3], q=Q((0.3456789,), (-37,))),
        )
        graph = import_bytes(build_model(tensors, nodes))
        p = prepare_graph(graph).nodes[0].integers
        a, w, o = (graph.tensors[i].quantization.scales[0] for i in (0, 1, 3))
        self.assertNotEqual(
            quantize_multiplier(a * w / o), quantize_multiplier(f32(a * w) / o)
        )
        self.assertEqual(
            (p["output_multiplier"], p["output_shift"]),
            quantize_multiplier(f32(a * w) / o),
        )
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "fc.tflite"
            model.write_bytes(build_model(tensors, nodes))
            capture_parameters(model, Path(directory) / "capture", self.record)

    def test_multiplier_preparation_flush_and_carry(self):
        self.assertEqual(quantize_multiplier(0), (0, 0))
        self.assertEqual(quantize_multiplier(1), (1 << 30, 1))
        self.assertEqual(quantize_multiplier(0.5), (1 << 30, 0))
        self.assertEqual(quantize_multiplier(2**-40), (0, 0))
        self.assertEqual(quantize_multiplier(1 - 2**-40), (1 << 30, 1))
        for value in (-1, float("nan"), float("inf"), 2**31):
            with self.assertRaises(ModelError):
                quantize_multiplier(value)

    def test_rounding_ties_and_saturating_high_multiply(self):
        self.assertEqual(
            [rounding_divide(x, 1) for x in (-3, -1, 1, 3)], [-2, -1, 1, 2]
        )
        self.assertEqual(high_mul(I32_MIN, I32_MIN), I32_MAX)
        self.assertEqual(high_mul(-1, 1 << 30), 0)
        self.assertEqual(high_mul(1, 1 << 30), 1)
        self.assertEqual(requantize(-3, 1 << 30, -1), -1)
        self.assertEqual(requantize(3, 1 << 30, -1), 1)

    def test_requantization_native_directed_all_observed_pairs_and_fuzz(self):
        pairs = {(1 << 30, s) for s in range(-31, 31)}
        for node in self.prepared.nodes:
            p = node.integers
            pairs.update(zip(p.get("multipliers", []), p.get("shifts", [])))
            for prefix, suffix in (
                ("output", "shift"),
                ("input1", "shift"),
                ("input2", "shift"),
                ("requantize_output", "shift"),
                ("input", "left_shift"),
            ):
                if f"{prefix}_multiplier" in p:
                    pairs.add((p[f"{prefix}_multiplier"], p[f"{prefix}_{suffix}"]))
        rng = random.Random(17)
        result = ctypes.c_int32()
        count = 0
        for multiplier, shift in sorted(pairs):
            low, high = -(1 << (31 - max(shift, 0))), I32_MAX // (1 << max(shift, 0))
            values = {
                low,
                low + 1,
                high - 1,
                high,
                -129,
                -128,
                -127,
                -3,
                -2,
                -1,
                0,
                1,
                2,
                3,
                126,
                127,
                128,
            }
            values.update(rng.randint(low, high) for _ in range(32))
            for x in values:
                if low <= x <= high:
                    self.assertEqual(
                        self.native.cc_requantize(
                            x, multiplier, shift, ctypes.byref(result)
                        ),
                        0,
                    )
                    self.assertEqual(
                        result.value,
                        requantize(x, multiplier, shift),
                        (x, multiplier, shift),
                    )
                    count += 1
        self.assertGreater(count, 200000)

    def test_overflow_rejected_without_output_mutation(self):
        result = ctypes.c_int32(77)
        for x, m, shift in (
            (I32_MAX, I32_MAX, 1),
            (I32_MIN, I32_MAX, 1),
            (1, 1, 31),
            (1, -1, 0),
            (1, 1, -32),
        ):
            with self.assertRaises(ModelError):
                requantize(x, m, shift)
            self.assertEqual(
                self.native.cc_requantize(x, m, shift, ctypes.byref(result)), 1
            )
            self.assertEqual(result.value, 77)
        with self.assertRaises(ModelError):
            adjusted_bias([127] * 100000, 128, I32_MAX)
        tensors, nodes = conv_fixture()
        with self.assertRaisesRegex(ModelError, "INT32"):
            prepare_graph(import_bytes(build_model(tensors, nodes)))

    def test_real_model_range_proofs_and_safe_adjusted_bias_selection(self):
        corrected = []
        for node, params in zip(self.graph.nodes, self.prepared.nodes):
            self.assertTrue(
                all(0 <= b <= I32_MAX for b in params.accumulator_abs_bounds)
            )
            if params.adjusted_biases is not None:
                corrected.append(node.index)
                self.assertEqual(node.kind, "CONV_2D")
                self.assertEqual(
                    self.graph.tensors[node.input("weights")].shape[1:3], (1, 1)
                )
                self.assertFalse(any(vars(node.padding).values()))
        self.assertIn(4, corrected)
        self.assertIn(58, corrected)
        self.assertIsNone(self.prepared.nodes[1].adjusted_biases)
        self.assertIsNone(self.prepared.nodes[8].adjusted_biases)

    def test_dot_adjusted_bias_extremes_long_accumulations_absent_bias(self):
        rng = random.Random(42)
        output = ctypes.c_int32()
        for count in (1, 3, 8, 16, 320, 1280, 65536):
            weights = [rng.randrange(-128, 128) for _ in range(count)]
            for zero in (-128, -17, 0, 127):
                for value in (-128, 127, zero):
                    inputs = [value] * count
                    for bias in (None, -12345, 12345):
                        expected = dot(inputs, weights, -zero, bias)
                        corrected = adjusted_bias(weights, -zero, bias)
                        self.assertEqual(expected, dot(inputs, weights, 0, corrected))
                        self.assertEqual(
                            self.native.cc_dot(
                                array8(inputs),
                                array8(weights),
                                count,
                                -zero,
                                bias or 0,
                                ctypes.byref(output),
                            ),
                            0,
                        )
                        self.assertEqual(output.value, expected)
        with self.assertRaises(ModelError):
            dot([127] * 100000, [127] * 100000, 128)

    def test_add_differing_scales_offsets_clamps_and_rounding(self):
        rng = random.Random(51)
        out = ctypes.c_int32()
        for node in self.prepared.nodes:
            if node.kind != "ADD":
                continue
            p = node.integers
            args = add_params(p)
            for x, y in [
                (x, y)
                for x in (-128, -127, -1, 0, 1, 126, 127, -p["input1_offset"])
                for y in (-128, -127, -1, 0, 1, 126, 127, -p["input2_offset"])
            ] + [
                (rng.randrange(-128, 128), rng.randrange(-128, 128))
                for _ in range(1000)
            ]:
                self.assertEqual(self.native.cc_add(x, y, args, ctypes.byref(out)), 0)
                self.assertEqual(out.value, add_scalar(x, y, p))

    def test_pool_positive_negative_ties_extremes_and_clamps(self):
        output = ctypes.c_int32()
        for values in (
            [-128],
            [127],
            [0],
            [-1, 0],
            [1, 0],
            [-128, 127],
            [-128] * 49,
            [127] * 49,
            list(range(-128, 128)),
            [1, 2, 3, 4],
        ):
            for minimum, maximum in ((-128, 127), (-13, 27), (0, 127)):
                self.assertEqual(
                    self.native.cc_pool(
                        array8(values),
                        len(values),
                        minimum,
                        maximum,
                        ctypes.byref(output),
                    ),
                    0,
                )
                self.assertEqual(output.value, average_pool(values, minimum, maximum))
        self.assertEqual(average_pool([-1, 0]), -1)
        self.assertEqual(average_pool([1, 0]), 1)
        with self.assertRaises(ModelError):
            average_pool([])

    def test_padded_borders_skip_taps_or_quantized_zero_no_full_filter_correction(self):
        pixels = [-9, -8, -7, -6]
        weights = list(range(1, 10))
        output = array8([0] * 4)
        for zero in (-128, -9, 0, 127):
            for bias in (None, -31, 31):
                native_bias = ctypes.c_int32(bias or 0)
                self.assertEqual(
                    self.native.cc_conv_border(
                        array8(pixels),
                        array8(weights),
                        -zero,
                        ctypes.byref(native_bias) if bias is not None else None,
                        output,
                    ),
                    0,
                )
                for y in range(2):
                    for x in range(2):
                        full, valid_x, valid_w = [], [], []
                        for ky in range(3):
                            for kx in range(3):
                                iy, ix = y + ky - 1, x + kx - 1
                                valid = 0 <= iy < 2 and 0 <= ix < 2
                                full.append(pixels[iy * 2 + ix] if valid else zero)
                                if valid:
                                    valid_x.append(pixels[iy * 2 + ix])
                                    valid_w.append(weights[ky * 3 + kx])
                        expected = dot(valid_x, valid_w, -zero, bias)
                        self.assertEqual(
                            dot(full, weights, 0, adjusted_bias(weights, -zero, bias)),
                            expected,
                        )
                        self.assertEqual(output[y * 2 + x], clamp(expected, -128, 127))
                        if zero == -9:
                            self.assertNotEqual(
                                dot(
                                    valid_x,
                                    valid_w,
                                    0,
                                    adjusted_bias(weights, -zero, bias),
                                ),
                                expected,
                            )

    def test_both_boundary_nodes_all_256_values_match_reference(self):
        source = (ctypes.c_uint8 * 256)(*range(256))
        shifted = (ctypes.c_uint8 * 256)()
        for direction in (True, False):
            self.assertEqual(
                self.native.cc_boundary(source, 256, direction, shifted), 0
            )
            self.assertEqual(bytes(shifted), bytes(x ^ 128 for x in range(256)))

    def test_softmax_full_outputs_and_measured_known_exponent_failure(self):
        params = self.prepared.nodes[62].integers
        diagnostics = {}
        for case in self.manifest["cases"]:
            directory = self.capture / case["name"]
            input_data = (directory / "node_61_output_0_tensor_162.bin").read_bytes()
            output = array8([77] * 1000)
            total, exponent = ctypes.c_int32(), ctypes.c_int()
            status = self.native.cc_softmax(
                array8(signed(input_data)),
                1000,
                params["input_multiplier"],
                params["input_left_shift"],
                params["diff_min"],
                output,
                ctypes.byref(total),
                ctypes.byref(exponent),
            )
            diagnostics[case["name"]] = {
                "status": status,
                "sum_raw": total.value,
                "exponent": exponent.value,
            }
            if case["name"] == "zero_point":
                self.assertEqual((status, exponent.value), (2, 32))
                self.assertEqual(list(output), [77] * 1000)
            else:
                self.assertEqual(status, 0)
                self.assertEqual(
                    bytes(output),
                    (directory / "node_62_output_0_tensor_163.bin").read_bytes(),
                )
        (NATIVE / "softmax-diagnostics.json").write_text(
            json.dumps(diagnostics, indent=2) + "\n"
        )

    def test_independent_scalar_representative_nodes_captured_outputs(self):
        # Compute selected complete dot products at corners and interior pixels,
        # including real 3x3/5x5 padding, channels, bias, shifts, and clamps.
        for case in self.manifest["cases"]:
            directory = self.capture / case["name"]
            records = {r["tensor"]: r for r in case["tensors"]}
            for index in (1, 4, 8, 15, 58, 61):
                node, prepared = self.graph.nodes[index], self.prepared.nodes[index]
                params = prepared.integers
                source = self.graph.tensors[node.input("input")]
                weights = self.graph.tensors[node.input("weights")]
                out_tensor = self.graph.tensors[node.outputs[0]]
                xs = signed((directory / records[source.index]["file"]).read_bytes())
                expected = signed(
                    (directory / records[out_tensor.index]["file"]).read_bytes()
                )
                ws, biases = (
                    self.graph.constant_values(weights.index),
                    self.graph.constant_values(node.input("bias")),
                )
                channels = out_tensor.shape[-1]
                positions = (
                    [(0, 0)]
                    if node.kind == "FULLY_CONNECTED"
                    else [
                        (0, 0),
                        (out_tensor.shape[1] // 2, out_tensor.shape[2] // 2),
                        (out_tensor.shape[1] - 1, out_tensor.shape[2] - 1),
                    ]
                )
                for y, x in positions:
                    for c in (0, channels // 2, channels - 1):
                        if node.kind == "FULLY_CONNECTED":
                            pairs = list(zip(xs, ws[c * len(xs) : (c + 1) * len(xs)]))
                        else:
                            pairs = []
                            _, ih, iw, ic = source.shape
                            _, kh, kw, _ = weights.shape
                            for ky in range(kh):
                                for kx in range(kw):
                                    iy = (
                                        y * node.options.stride_h
                                        + ky * node.options.dilation_h
                                        - node.padding.top
                                    )
                                    ix = (
                                        x * node.options.stride_w
                                        + kx * node.options.dilation_w
                                        - node.padding.left
                                    )
                                    if not (0 <= iy < ih and 0 <= ix < iw):
                                        continue
                                    cs = (
                                        [c // node.options.depth_multiplier]
                                        if node.kind == "DEPTHWISE_CONV_2D"
                                        else range(ic)
                                    )
                                    for cin in cs:
                                        wi = (
                                            (ky * kw + kx) * channels + c
                                            if node.kind == "DEPTHWISE_CONV_2D"
                                            else ((c * kh + ky) * kw + kx) * ic + cin
                                        )
                                        pairs.append(
                                            (xs[(iy * iw + ix) * ic + cin], ws[wi])
                                        )
                        inputs, row = zip(*pairs)
                        accumulator = dot(
                            inputs, row, -params["input_zero_point"], biases[c]
                        )
                        if prepared.adjusted_biases is not None:
                            self.assertEqual(
                                accumulator,
                                dot(inputs, row, 0, prepared.adjusted_biases[c]),
                            )
                        multiplier = (
                            params["output_multiplier"]
                            if node.kind == "FULLY_CONNECTED"
                            else params["multipliers"][c]
                        )
                        shift = (
                            params["output_shift"]
                            if node.kind == "FULLY_CONNECTED"
                            else params["shifts"][c]
                        )
                        output = clamp(
                            requantize(accumulator, multiplier, shift)
                            + prepared.output_offset,
                            params["output_activation_min"],
                            params["output_activation_max"],
                        )
                        offset = (
                            c
                            if node.kind == "FULLY_CONNECTED"
                            else (y * out_tensor.shape[2] + x) * channels + c
                        )
                        self.assertEqual(
                            output, expected[offset], (case["name"], index, y, x, c)
                        )

    def test_native_numeric_sanitizers(self):
        result = subprocess.run(
            [str(ROOT / self.record["sanitized"])],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        self.assertIn("ASan/UBSan numeric helpers: PASS", result.stdout)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
