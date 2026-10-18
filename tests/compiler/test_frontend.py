"""Stage 1: actual model parity, source FlatBuffer rejection, and stable IR."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import struct
import sys
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tflite
from fixtures.tflite_builder import O, Q, T, build_model

from compiler.cli import main
from compiler.export import dot_graph, export_graph, node_table
from compiler.frontend import DEPENDENCIES, import_bytes, import_model
from compiler.ir import Graph, ModelError, Padding
from compiler.validation import validate_graph, validate_project_model

MODEL = ROOT / "models/efficientnet-lite0-int8.tflite"
AUDIT = ROOT / "models/efficientnet-lite0-int8.audit.json"


def conv_fixture(**op_changes):
    tensors = (
        T((1, 3, 3, 2), q=Q(zero_points=(-9,))),
        T((2, 1, 1, 2), data=bytes([255, 127, 128, 0]), q=Q((0.5, 0.5), (0, 0))),
        T(
            (2,),
            "INT32",
            struct.pack("<ii", -(1 << 31), (1 << 31) - 1),
            Q((0.25, 0.25), (0, 0)),
        ),
        T((1, 3, 3, 2)),
    )
    return tensors, (O("CONV_2D", (0, 1, 2), (3,), **op_changes),)


def depthwise_fixture(multiplier=1, **op_changes):
    channels = 2 * multiplier
    tensors = (
        T((1, 3, 3, 2)),
        T(
            (1, 3, 3, channels),
            data=bytes([1]) * (9 * channels),
            q=Q((0.5,) * channels, (0,) * channels, 3),
        ),
        T(
            (channels,),
            "INT32",
            bytes(4 * channels),
            Q((0.25,) * channels, (0,) * channels),
        ),
        T((1, 3, 3, channels)),
    )
    return tensors, (
        O(
            "DEPTHWISE_CONV_2D",
            (0, 1, 2),
            (3,),
            options={"depth_multiplier": multiplier},
            **op_changes,
        ),
    )


def add_fixture(**op_changes):
    tensors = (T((1, 2), q=Q((0.5,), (-9,))), T((1, 2), q=Q((0.25,), (7,))), T((1, 2)))
    return tensors, (O("ADD", (0, 1), (2,), **op_changes),)


def fc_fixture(**op_changes):
    tensors = (
        T((1, 2)),
        T((3, 2), data=bytes([1, 2, 3, 4, 5, 6])),
        T((3,), "INT32", bytes(12), Q((0.25,), (0,))),
        T((1, 3)),
    )
    return tensors, (O("FULLY_CONNECTED", (0, 1, 2), (3,), **op_changes),)


def reshape_fixture(**op_changes):
    tensors = (
        T((1, 1, 1, 2)),
        T((2,), "INT32", struct.pack("<ii", 1, 2), None),
        T((1, 2)),
    )
    return tensors, (O("RESHAPE", (0, 1), (2,), **op_changes),)


def quantize_fixture(**op_changes):
    tensors = (T((1, 2), "UINT8", q=Q((0.5,), (131,))), T((1, 2), q=Q((0.5,), (3,))))
    return tensors, (O("QUANTIZE", (0,), (1,), **op_changes),)


def pool_fixture(**op_changes):
    return (T((1, 3, 3, 2)), T((1, 1, 1, 2))), (
        O("AVERAGE_POOL_2D", (0,), (1,), **op_changes),
    )


def softmax_fixture(**op_changes):
    return (T((1, 4)), T((1, 4), q=Q((1 / 256,), (-128,)))), (
        O("SOFTMAX", (0,), (1,), **op_changes),
    )


class ActualModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = MODEL.read_bytes()
        cls.graph = import_bytes(cls.data)
        cls.audit = json.loads(AUDIT.read_text())

    def test_exact_frozen_model_inventory(self):
        graph = self.graph
        validate_project_model(graph, self.audit)
        self.assertEqual(
            (len(graph.nodes), len(graph.tensors), graph.subgraph), (64, 166, 0)
        )
        self.assertEqual(
            dict(Counter(node.kind for node in graph.nodes)),
            self.audit["operator_counts"],
        )
        self.assertEqual(graph.model_sha256, self.audit["sha256"])
        self.assertEqual((graph.inputs, graph.outputs), ((164,), (165,)))

    def test_every_tensor_and_constant_matches_source_bytes_and_metadata(self):
        source = tflite.Model.GetRootAsModel(self.data, 0)
        subgraph = source.Subgraphs(0)
        for tensor in self.graph.tensors:
            with self.subTest(tensor=tensor.index):
                original = subgraph.Tensors(tensor.index)
                self.assertEqual(tensor.name, original.Name().decode())
                self.assertEqual(tensor.shape, tuple(original.ShapeAsNumpy()))
                self.assertEqual(tensor.buffer, original.Buffer())
                q = original.Quantization()
                self.assertEqual(
                    tensor.quantization.scales,
                    tuple(float(q.Scale(i)) for i in range(q.ScaleLength())),
                )
                self.assertEqual(
                    tensor.quantization.zero_points,
                    tuple(q.ZeroPoint(i) for i in range(q.ZeroPointLength())),
                )
                self.assertEqual(
                    tensor.quantization.quantized_dimension, q.QuantizedDimension()
                )
                self.assertEqual(
                    tensor.quantization.minimum,
                    tuple(q.Min(i) for i in range(q.MinLength())),
                )
                self.assertEqual(
                    tensor.quantization.maximum,
                    tuple(q.Max(i) for i in range(q.MaxLength())),
                )
                payload = source.Buffers(tensor.buffer)
                data = bytes(payload.DataAsNumpy()) if payload.DataLength() else b""
                self.assertEqual(self.graph.buffers[tensor.buffer].data, data)
                if tensor.storage == "constant":
                    self.assertEqual(len(data), tensor.byte_length)
        self.assertEqual(
            sum(len(buffer.data) for buffer in self.graph.buffers), 4697032
        )
        self.assertEqual(self.graph.constant_values(101), (1, 1280))

    def test_all_node_outputs_match_stage0_oracle_metadata(self):
        golden = json.loads(
            (ROOT / "tests/compiler/fixtures/oracle-golden.json").read_text()
        )
        for expected in golden["node_outputs"]:
            node = self.graph.nodes[expected["node"]]
            tensor = self.graph.tensors[node.outputs[0]]
            self.assertEqual(
                (
                    node.kind,
                    tensor.index,
                    tensor.dtype,
                    list(tensor.shape),
                    tensor.byte_length,
                ),
                (
                    expected["operator"],
                    expected["tensor"],
                    expected["type"],
                    expected["shape"],
                    expected["bytes"],
                ),
            )

    def test_all_nine_residual_edges_are_actual_graph_edges(self):
        expected = {
            10: (9, 6),
            17: (16, 13),
            24: (23, 20),
            28: (27, 24),
            35: (34, 31),
            39: (38, 35),
            46: (45, 42),
            50: (49, 46),
            54: (53, 50),
        }
        actual = {}
        for node in self.graph.nodes:
            if node.kind == "ADD":
                actual[node.index] = tuple(
                    self.graph.tensors[operand.tensor].producer
                    for operand in node.inputs
                )
                for operand in node.inputs:
                    self.assertIn(
                        node.index, self.graph.tensors[operand.tensor].consumers
                    )
        self.assertEqual(actual, expected)
        self.assertEqual(self.graph.tensors[107].consumers, (7, 10))
        self.assertEqual(self.graph.nodes[4].source_inputs, (104, 21, 55))

    def test_options_padding_axes_and_storage_remain_explicit(self):
        graph = self.graph
        self.assertEqual(graph.nodes[1].padding, Padding(0, 1, 0, 1))
        self.assertEqual(graph.nodes[4].options.fused_activation, "RELU6")
        self.assertEqual(graph.nodes[15].options.depth_multiplier, 1)
        self.assertEqual(graph.nodes[59].options.padding, "VALID")
        self.assertEqual(
            (graph.nodes[59].options.filter_h, graph.nodes[59].options.filter_w), (7, 7)
        )
        self.assertFalse(graph.nodes[61].options.keep_num_dims)
        self.assertTrue(graph.nodes[10].options.pot_scale_int16)
        self.assertEqual(graph.nodes[62].options.beta, 1.0)
        self.assertEqual(
            [graph.nodes[index].options_type for index in (0, 60, 63)], ["NONE"] * 3
        )
        self.assertEqual(graph.tensors[19].layout, "OHWI")
        self.assertEqual(graph.tensors[53].layout, "1HWO")
        self.assertEqual(graph.tensors[101].layout, "SHAPE")
        # Empty FlatBuffer buffer IDs do not imply shared runtime tensor addresses.
        self.assertEqual(graph.tensors[164].buffer, graph.tensors[165].buffer)
        self.assertEqual(
            (graph.tensors[164].producer, graph.tensors[165].producer), (None, 63)
        )
        self.assertFalse(Graph.CAPABILITIES["prepared_parameters"])
        self.assertFalse(Graph.CAPABILITIES["memory_plan"])
        self.assertFalse(Graph.CAPABILITIES["inference_codegen"])

    def test_canonical_ir_roundtrip_and_path_independent_hash(self):
        canonical = self.graph.to_json()
        restored = Graph.from_json(canonical)
        self.assertEqual(restored, self.graph)
        self.assertEqual(restored.to_json(), canonical)
        self.assertEqual(restored.sha256, self.graph.sha256)
        with tempfile.TemporaryDirectory(prefix="compiler-model-copy-") as temporary:
            copy = Path(temporary) / "different-model-name.tflite"
            copy.write_bytes(self.data)
            self.assertEqual(import_model(copy).to_json(), canonical)

    def test_deterministic_artifacts_and_residual_dot_edges(self):
        with tempfile.TemporaryDirectory(prefix="compiler-export-") as temporary:
            root = Path(temporary)
            first, second = root / "first", root / "second"
            manifest = export_graph(self.graph, first)
            export_graph(self.graph, second)
            for name, digest in manifest["artifacts"].items():
                self.assertEqual(
                    (first / name).read_bytes(), (second / name).read_bytes()
                )
                self.assertEqual(
                    hashlib.sha256((first / name).read_bytes()).hexdigest(), digest
                )
            self.assertEqual(manifest["dependencies"], DEPENDENCIES)
            self.assertIsNone(manifest["memory_plan_sha256"])
            self.assertIsNone(manifest["elf_sha256"])
            self.assertEqual(
                Graph.from_json((first / "graph_ir.json").read_text()), self.graph
            )
        dot = dot_graph(self.graph)
        self.assertIn('t107 -> n10 [label="rhs"]', dot)
        self.assertIn('n6 -> t107 [label="output0"]', dot)
        table = node_table(self.graph)
        self.assertEqual(
            sum(
                line.startswith("| ") and line[2:3].isdigit()
                for line in table.splitlines()
            ),
            64,
        )

    def test_cli_validation_inspection_and_backend_gate(self):
        for command in ("validate", "inspect"):
            with (
                self.subTest(command=command),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(main([command, str(MODEL)]), 0)
                self.assertIn("64", output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as error:
                main(["generate", str(MODEL), "--config", "X5"])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("invalid choice", errors.getvalue())


class SupportedFixtureTests(unittest.TestCase):
    def test_each_supported_operator_decodes_from_a_small_flatbuffer(self):
        for make in (
            conv_fixture,
            depthwise_fixture,
            add_fixture,
            fc_fixture,
            reshape_fixture,
            quantize_fixture,
            pool_fixture,
            softmax_fixture,
        ):
            with self.subTest(fixture=make.__name__):
                tensors, nodes = make()
                graph = import_bytes(
                    build_model(
                        tensors, nodes, inputs=(0, 1) if make == add_fixture else (0,)
                    )
                )
                self.assertEqual(graph.nodes[0].kind, nodes[0].kind)
                self.assertEqual(validate_graph(graph), graph)

    def test_optional_bias_is_preserved_as_omitted_or_minus_one(self):
        for make in (conv_fixture, depthwise_fixture, fc_fixture):
            tensors, (node,) = make()
            for source_inputs in ((0, 1), (0, 1, -1)):
                with self.subTest(kind=node.kind, inputs=source_inputs):
                    graph = import_bytes(
                        build_model(tensors, (replace(node, inputs=source_inputs),))
                    )
                    self.assertIsNone(graph.nodes[0].input("bias"))
                    self.assertEqual(graph.nodes[0].source_inputs, source_inputs)

    def test_integer_constants_decode_signed_little_endian(self):
        graph = import_bytes(build_model(*conv_fixture()))
        self.assertEqual(graph.constant_values(1), (-1, 127, -128, 0))
        self.assertEqual(graph.constant_values(2), (-(1 << 31), (1 << 31) - 1))
        with self.assertRaisesRegex(ModelError, "not a constant"):
            graph.constant_values(0)

    def test_modern_and_legacy_builtin_code_forms_match_pinned_tflm(self):
        tensors, nodes = conv_fixture()
        for modern in (False, True):
            with self.subTest(modern_code_only=modern):
                graph = import_bytes(
                    build_model(tensors, nodes, modern_code_only=modern)
                )
                self.assertEqual(graph.nodes[0].kind, "CONV_2D")
                self.assertEqual(graph.operator_codes[0].builtin_code, 3)
        # The real graph uses only the deprecated field, also handled by TFLM's max rule.
        real = import_model(MODEL)
        self.assertTrue(
            all(code.builtin_code_field == 0 for code in real.operator_codes)
        )

    def test_dilation_stride_and_asymmetric_padding_are_inferred(self):
        tensors, nodes = conv_fixture(
            options={"stride_h": 2, "stride_w": 2, "dilation_h": 2, "dilation_w": 2}
        )
        tensors = (
            replace(tensors[0], shape=(1, 4, 4, 2)),
            replace(tensors[1], shape=(2, 3, 3, 2), data=bytes(36)),
            tensors[2],
            replace(tensors[3], shape=(1, 2, 2, 2)),
        )
        graph = import_bytes(build_model(tensors, nodes))
        self.assertEqual(graph.nodes[0].padding, Padding(1, 2, 1, 2))
        graph = import_bytes(build_model(*depthwise_fixture(multiplier=2)))
        self.assertEqual(graph.nodes[0].options.depth_multiplier, 2)
        self.assertEqual(graph.tensors[3].shape[-1], 4)

    def test_reshape_shape_tensor_and_option_with_inferred_dimension(self):
        tensors, (node,) = reshape_fixture()
        variants = (
            replace(node, inputs=(0,), options={"new_shape": (-1, 2)}),
            replace(node, options={"new_shape": (1, 2)}),
            replace(node, inputs=(0, -1), options={"new_shape": (1, 2)}),
        )
        for variant in variants:
            with self.subTest(inputs=variant.inputs, options=variant.options):
                graph = import_bytes(build_model(tensors, (variant,)))
                self.assertEqual(graph.tensors[2].shape, (1, 2))
                self.assertEqual(graph.tensors[2].storage, "runtime")

    def test_residual_add_preserves_differing_scales_and_asymmetric_zero_points(self):
        graph = import_bytes(build_model(*add_fixture(), inputs=(0, 1)))
        self.assertEqual(graph.tensors[0].quantization.zero_points, (-9,))
        self.assertEqual(graph.tensors[1].quantization.zero_points, (7,))
        self.assertNotEqual(
            graph.tensors[0].quantization.scales, graph.tensors[1].quantization.scales
        )


class RejectedSourceTests(unittest.TestCase):
    def reject(self, tensors, nodes, message, **kwargs):
        with self.assertRaisesRegex(ModelError, message):
            import_bytes(build_model(tensors, nodes, **kwargs))

    def test_rejects_unsupported_version_custom_and_control_flow(self):
        tensors, nodes = conv_fixture(version=99)
        self.reject(tensors, nodes, "unsupported CONV_2D version 99")
        tensors = (T((1, 2)), T((1, 2)))
        self.reject(
            tensors,
            (O("CUSTOM", (0,), (1,), custom_code="fixture"),),
            "custom operators",
        )
        self.reject(tensors, (O("IF", (0,), (1,)),), "unsupported IF")

    def test_rejects_multiple_subgraphs_and_schema_versions(self):
        tensors, nodes = conv_fixture()
        self.reject(tensors, nodes, "one static subgraph", subgraphs=2)
        self.reject(tensors, nodes, "schema version 4", schema_version=4)

    def test_rejects_dynamic_shapes_and_signatures(self):
        tensors, nodes = conv_fixture()
        variants = (
            replace(tensors[0], shape=(1, -1, 3, 2)),
            replace(tensors[0], shape=(1, 0, 3, 2)),
            replace(tensors[0], signature=(1, -1, 3, 2)),
        )
        for tensor in variants:
            with self.subTest(shape=tensor.shape, signature=tensor.signature):
                self.reject(
                    (tensor, *tensors[1:]), nodes, "static shapes|shape signature"
                )

    def test_rejects_bad_quantization_axis_count_and_scale(self):
        tensors, nodes = conv_fixture()
        variants = (
            Q((0.5, 0.5), (0, 0), 99),
            Q((0.5, 0.5), (0, 0), 3),
            Q((0.5, 0.5), (0,)),
            Q((0.0, 0.5), (0, 0)),
            Q((math.nan, 0.5), (0, 0)),
        )
        for quantization in variants:
            with self.subTest(q=quantization):
                self.reject(
                    (tensors[0], replace(tensors[1], q=quantization), *tensors[2:]),
                    nodes,
                    "quantized dimension|count mismatch|positive|non-finite",
                )

    def test_rejects_missing_quantization_and_out_of_range_zero_points(self):
        tensors, nodes = conv_fixture()
        for q in (None, Q((0.5,), (128,)), Q((), ())):
            with self.subTest(q=q):
                self.reject(
                    (replace(tensors[0], q=q), *tensors[1:]),
                    nodes,
                    "missing affine quantization|outside dtype range",
                )

    def test_rejects_asymmetric_weights_and_incorrect_bias_metadata(self):
        tensors, nodes = conv_fixture()
        self.reject(
            (tensors[0], replace(tensors[1], q=Q((0.5, 0.5), (1, 0))), *tensors[2:]),
            nodes,
            "symmetric zero-points",
        )
        self.reject(
            (*tensors[:2], replace(tensors[2], q=Q((0.5, 0.5), (0, 0))), tensors[3]),
            nodes,
            "bias scales differ",
        )
        self.reject(
            (*tensors[:2], replace(tensors[2], q=Q((0.25, 0.25), (1, 0))), tensors[3]),
            nodes,
            "bias zero-points",
        )

    def test_rejects_bad_constant_lengths_missing_and_external_buffers(self):
        tensors, nodes = conv_fixture()
        self.reject(
            (tensors[0], replace(tensors[1], data=b"\x01"), *tensors[2:]),
            nodes,
            "constant byte length",
        )
        self.reject(
            (tensors[0], replace(tensors[1], buffer_override=999), *tensors[2:]),
            nodes,
            "invalid buffer index",
        )
        self.reject(
            (tensors[0], replace(tensors[1], data=None), *tensors[2:]),
            nodes,
            "weights requires a nonempty constant buffer",
        )
        self.reject(tensors, nodes, "external buffer payload", external_buffer=True)

    def test_rejects_bad_output_shape_stride_dilation_and_grouping(self):
        tensors, (node,) = conv_fixture()
        self.reject(
            (*tensors[:3], replace(tensors[3], shape=(1, 2, 3, 2))),
            (node,),
            "output shape",
        )
        for values in (
            {"stride_h": 0},
            {"dilation_w": 0},
            {"padding": "VALID", "stride_h": -1},
        ):
            with self.subTest(options=values):
                self.reject(
                    tensors, (replace(node, options=values),), "positive integers"
                )
        self.reject(
            (
                tensors[0],
                replace(tensors[1], shape=(2, 1, 1, 1), data=bytes(2)),
                *tensors[2:],
            ),
            (node,),
            "per-axis scale count|convolution input channels",
        )

    def test_rejects_bad_depth_multiplier_and_weight_axis(self):
        tensors, (node,) = depthwise_fixture()
        self.reject(
            tensors,
            (replace(node, options={"depth_multiplier": 2}),),
            "depth multiplier/filter channels",
        )
        self.reject(
            tensors,
            (replace(node, options={"depth_multiplier": 0}),),
            "depth multiplier must be positive",
        )
        self.reject(
            (tensors[0], replace(tensors[1], q=Q((0.5, 0.5), (0, 0), 0)), *tensors[2:]),
            (node,),
            "per-axis scale count",
        )

    def test_rejects_ignored_unsupported_and_mismatched_options(self):
        tensors, (node,) = conv_fixture()
        variants = (
            (replace(node, options=None), "missing required builtin options"),
            (
                replace(node, options_type_override=tflite.BuiltinOptions.AddOptions),
                "union discriminator mismatch",
            ),
            (
                replace(node, unknown_option_field=True),
                "unsupported populated Conv2DOptions field",
            ),
            (replace(node, secondary_options=1), "secondary builtin options"),
            (replace(node, custom_options=b"\x01"), "custom operator options"),
            (
                replace(node, mutating_inputs=(False, False, False)),
                "mutating variable inputs",
            ),
            (replace(node, intermediates=(0,)), "intermediates"),
            (
                replace(node, options={"fused_activation": "TANH"}),
                "unsupported fused activation",
            ),
            (
                replace(node, options={"quantized_bias_type": "INT64"}),
                "unsupported quantized_bias_type",
            ),
        )
        for variant, error in variants:
            with self.subTest(error=error):
                self.reject(tensors, (variant,), error)

    def test_rejects_float_variable_sparse_and_custom_quantization(self):
        tensors, nodes = conv_fixture()
        for tensor, error in (
            (replace(tensors[0], dtype="FLOAT32"), "unsupported dtype"),
            (replace(tensors[0], variable=True), "variable, sparse"),
            (replace(tensors[0], sparse=True), "variable, sparse"),
            (replace(tensors[0], q=Q(details_type=1)), "custom quantization"),
        ):
            with self.subTest(error=error):
                self.reject((tensor, *tensors[1:]), nodes, error)

    def test_rejects_broadcast_add_and_pool_quantization_changes(self):
        tensors, nodes = add_fixture()
        self.reject(
            (tensors[0], replace(tensors[1], shape=(1, 1)), tensors[2]),
            nodes,
            "broadcast ADD",
            inputs=(0, 1),
        )
        tensors, nodes = pool_fixture()
        self.reject(
            (tensors[0], replace(tensors[1], q=Q((0.25,), (0,)))),
            nodes,
            "quantization must match",
        )

    def test_rejects_unsupported_fc_options(self):
        tensors, (node,) = fc_fixture()
        for options in (
            {"keep_num_dims": True},
            {"asymmetric_quantize_inputs": True},
            {"weights_format": "SHUFFLED4x16INT8"},
        ):
            with self.subTest(options=options):
                self.reject(
                    tensors, (replace(node, options=options),), "only DEFAULT weights"
                )

    def test_rejects_reshape_conflicts_missing_shape_and_multiple_inference(self):
        tensors, (node,) = reshape_fixture()
        self.reject(
            tensors,
            (replace(node, options={"new_shape": (2, 1)}),),
            "target shape differs",
        )
        self.reject(tensors, (replace(node, inputs=(0,)),), "missing constant shape")
        self.reject(
            tensors,
            (replace(node, inputs=(0,), options={"new_shape": (-1, -1)}),),
            "multiple inferred dimensions",
        )
        self.reject(
            (
                tensors[0],
                replace(tensors[1], data=struct.pack("<ii", 2, 1)),
                tensors[2],
            ),
            (node,),
            "target shape differs",
        )

    def test_rejects_invalid_softmax_and_boundary_contracts(self):
        tensors, (node,) = softmax_fixture()
        for beta in (0.0, -1.0, math.nan):
            with self.subTest(beta=beta):
                self.reject(
                    tensors,
                    (replace(node, options={"beta": beta}),),
                    "beta must be positive and finite",
                )
        self.reject(
            (tensors[0], replace(tensors[1], q=Q((1 / 128,), (-128,)))),
            (node,),
            "Softmax output requires",
        )
        tensors, nodes = quantize_fixture()
        self.reject(
            (tensors[0], replace(tensors[1], q=Q((0.5,), (4,)))),
            nodes,
            "128-point representation shift",
        )
        self.reject(
            (tensors[0], replace(tensors[1], q=Q((0.25,), (3,)))),
            nodes,
            "identical shape/scale",
        )

    def test_rejects_invalid_indices_missing_producers_and_cyclic_edges(self):
        tensors = (T((1, 2)), T((1, 2)), T((1, 2)))
        variants = (
            ((O("ADD", (0, 999), (2,)),), "invalid input tensor index"),
            ((O("ADD", (0, 0), (-1,)),), "invalid output tensor index"),
            ((O("ADD", (-1, 0), (2,)),), "required input lhs is absent"),
            ((O("ADD", (0, 0, 0), (2,)),), "invalid input arity"),
            ((O("ADD", (0, 1), (2,)),), "runtime tensor has no producer"),
            ((O("ADD", (0, 2), (1,)), O("ADD", (1, 0), (2,))), "non-topological"),
            ((O("ADD", (0, 0), (1,)), O("ADD", (0, 0), (1,))), "multiple producers"),
            ((O("ADD", (0, 0), (0,)),), "cannot overwrite a graph input"),
        )
        for nodes, error in variants:
            with self.subTest(error=error):
                self.reject(tensors, nodes, error, outputs=(2,))

    def test_rejects_truncated_buffers_bad_root_and_out_of_bounds_vectors(self):
        data = build_model(*conv_fixture())
        for malformed in (
            b"",
            b"12345678",
            data[:8],
            data[: len(data) // 2],
            struct.pack("<I", 0xFFFFFFFF) + data[4:],
        ):
            with self.subTest(size=len(malformed)), self.assertRaises(ModelError):
                import_bytes(malformed)
        corrupt = bytearray(data)
        model = tflite.Model.GetRootAsModel(corrupt, 0)
        tensor = model.Subgraphs(0).Tensors(0)
        offset = tensor._tab.Offset(4)
        vector = tensor._tab.Vector(offset)
        struct.pack_into("<I", corrupt, vector - 4, 0xFFFFFFFF)
        with self.assertRaisesRegex(ModelError, "vector outside FlatBuffer"):
            import_bytes(corrupt)

    def test_cli_rejects_another_model_before_creating_exports(self):
        with tempfile.TemporaryDirectory(prefix="compiler-reject-cli-") as temporary:
            root = Path(temporary)
            source, destination = root / "other.tflite", root / "no-artifacts"
            source.write_bytes(build_model(*conv_fixture()))
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(
                    main(["import", str(source), "--output-dir", str(destination)]), 1
                )
            self.assertIn("differs from the tracked", errors.getvalue())
            self.assertFalse(destination.exists())


class SerializedIRTests(unittest.TestCase):
    def test_roundtrip_checks_constant_bytes_capabilities_and_derived_edges(self):
        graph = import_bytes(build_model(*conv_fixture()))
        self.assertEqual(Graph.from_json(graph.to_json()), graph)
        for corruption, error in (
            ("buffer", "data/hash mismatch"),
            ("capabilities", "capability claims"),
            ("producer", "derived producer/consumer"),
            ("padding", "inferred padding"),
        ):
            with self.subTest(corruption=corruption):
                record = graph.to_dict()
                if corruption == "buffer":
                    record["buffers"][1]["data_hex"] = "00"
                elif corruption == "capabilities":
                    record["capabilities"]["prepared_parameters"] = True
                elif corruption == "producer":
                    record["tensors"][3]["producer"] = None
                else:
                    record["nodes"][0]["padding"]["top"] = 99
                with self.assertRaisesRegex(ModelError, error):
                    Graph.from_json(json.dumps(record))

    def test_roundtrip_rejects_unknown_ir_schema_and_fields(self):
        graph = import_bytes(build_model(*quantize_fixture()))
        for field, value, error in (
            ("ir_schema_version", 99, "schema version"),
            ("unknown_field", True, "serialized graph IR"),
            ("byte_order", "big", "byte order"),
        ):
            record = graph.to_dict()
            record[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ModelError, error):
                Graph.from_json(json.dumps(record))


if __name__ == "__main__":
    unittest.main()
