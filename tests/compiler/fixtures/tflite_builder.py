"""Construct tiny source FlatBuffers so frontend tests exercise real decoding."""

from __future__ import annotations

from dataclasses import dataclass, field

import flatbuffers
import tflite


@dataclass(frozen=True)
class Q:
    scales: tuple[float, ...] = (0.5,)
    zero_points: tuple[int, ...] = (0,)
    axis: int = 0
    details_type: int = 0


@dataclass(frozen=True)
class T:
    shape: tuple[int, ...]
    dtype: str = "INT8"
    data: bytes | None = None
    q: Q | None = Q()
    name: str = "fixture"
    signature: tuple[int, ...] | None = None
    variable: bool = False
    sparse: bool = False
    buffer_override: int | None = None


@dataclass(frozen=True)
class O:
    kind: str
    inputs: tuple[int, ...]
    outputs: tuple[int, ...]
    options: dict | None = field(default_factory=dict)
    version: int | None = None
    options_type_override: int | None = None
    unknown_option_field: bool = False
    custom_options: bytes = b""
    custom_code: str | None = None
    secondary_options: int = 0
    mutating_inputs: tuple[bool, ...] = ()
    intermediates: tuple[int, ...] = ()


VERSIONS = {
    "CONV_2D": 3,
    "DEPTHWISE_CONV_2D": 3,
    "ADD": 2,
    "AVERAGE_POOL_2D": 2,
    "FULLY_CONNECTED": 4,
    "RESHAPE": 1,
    "QUANTIZE": 1,
    "SOFTMAX": 2,
}
OPTION_CLASSES = {
    "CONV_2D": "Conv2DOptions",
    "DEPTHWISE_CONV_2D": "DepthwiseConv2DOptions",
    "ADD": "AddOptions",
    "AVERAGE_POOL_2D": "Pool2DOptions",
    "FULLY_CONNECTED": "FullyConnectedOptions",
    "RESHAPE": "ReshapeOptions",
    "QUANTIZE": "QuantizeOptions",
    "SOFTMAX": "SoftmaxOptions",
}
DEFAULT_OPTIONS = {
    "CONV_2D": {
        "padding": "SAME",
        "stride_h": 1,
        "stride_w": 1,
        "dilation_h": 1,
        "dilation_w": 1,
        "fused_activation": "NONE",
        "quantized_bias_type": "FLOAT32",
    },
    "DEPTHWISE_CONV_2D": {
        "padding": "SAME",
        "stride_h": 1,
        "stride_w": 1,
        "dilation_h": 1,
        "dilation_w": 1,
        "depth_multiplier": 1,
        "fused_activation": "NONE",
    },
    "ADD": {"fused_activation": "NONE", "pot_scale_int16": True},
    "AVERAGE_POOL_2D": {
        "padding": "VALID",
        "stride_h": 1,
        "stride_w": 1,
        "filter_h": 3,
        "filter_w": 3,
        "fused_activation": "NONE",
    },
    "FULLY_CONNECTED": {
        "fused_activation": "NONE",
        "weights_format": "DEFAULT",
        "keep_num_dims": False,
        "asymmetric_quantize_inputs": False,
        "quantized_bias_type": "FLOAT32",
    },
    "SOFTMAX": {"beta": 1.0},
    "RESHAPE": {},
    "QUANTIZE": {},
}
ACCESSORS = {
    "padding": "Padding",
    "stride_h": "StrideH",
    "stride_w": "StrideW",
    "dilation_h": "DilationHFactor",
    "dilation_w": "DilationWFactor",
    "fused_activation": "FusedActivationFunction",
    "depth_multiplier": "DepthMultiplier",
    "quantized_bias_type": "QuantizedBiasType",
    "filter_h": "FilterHeight",
    "filter_w": "FilterWidth",
    "weights_format": "WeightsFormat",
    "keep_num_dims": "KeepNumDims",
    "asymmetric_quantize_inputs": "AsymmetricQuantizeInputs",
    "beta": "Beta",
    "pot_scale_int16": "PotScaleInt16",
    "new_shape": "NewShape",
}


def vector(builder, values, kind="int32"):
    width = {"int32": 4, "float32": 4, "int64": 8, "offset": 4, "bool": 1}[kind]
    builder.StartVector(width, len(values), width)
    for value in reversed(values):
        {
            "int32": builder.PrependInt32,
            "float32": builder.PrependFloat32,
            "int64": builder.PrependInt64,
            "offset": builder.PrependUOffsetTRelative,
            "bool": builder.PrependBool,
        }[kind](value)
    return builder.EndVector()


def build_options(builder, op):
    if (
        op.kind not in OPTION_CLASSES
        or op.options is None
        or (op.kind in ("RESHAPE", "QUANTIZE") and not op.options)
    ):
        return tflite.BuiltinOptions.NONE, 0
    name = OPTION_CLASSES[op.kind]
    values = {**DEFAULT_OPTIONS[op.kind], **op.options}
    if "new_shape" in values:
        values["new_shape"] = vector(builder, values["new_shape"])
    if op.unknown_option_field:
        assert name == "Conv2DOptions"
        builder.StartObject(8)
    else:
        getattr(tflite, name + "Start")(builder)
    for key, value in values.items():
        if isinstance(value, str):
            enum = {
                "padding": tflite.Padding,
                "fused_activation": tflite.ActivationFunctionType,
                "weights_format": tflite.FullyConnectedOptionsWeightsFormat,
                "quantized_bias_type": tflite.TensorType,
            }[key]
            value = getattr(enum, value)
        getattr(tflite, name + "Add" + ACCESSORS[key])(builder, value)
    if op.unknown_option_field:
        builder.PrependInt32Slot(7, 42, 0)
    options = getattr(tflite, name + "End")(builder)
    return getattr(tflite.BuiltinOptions, name), options


def build_model(
    tensors: tuple[T, ...],
    nodes: tuple[O, ...],
    *,
    inputs=(0,),
    outputs=None,
    subgraphs=1,
    schema_version=3,
    modern_code_only=False,
    external_buffer=False,
) -> bytes:
    builder = flatbuffers.Builder(2048)
    buffers = []
    buffer_ids = []
    tflite.BufferStart(builder)
    buffers.append(tflite.BufferEnd(builder))
    for tensor in tensors:
        if tensor.data is None:
            buffer_ids.append(0)
        else:
            payload = builder.CreateByteVector(tensor.data)
            tflite.BufferStart(builder)
            tflite.BufferAddData(builder, payload)
            if external_buffer:
                tflite.BufferAddOffset(builder, 128)
                tflite.BufferAddSize(builder, len(tensor.data))
            buffer_ids.append(len(buffers))
            buffers.append(tflite.BufferEnd(builder))
    tensor_offsets = []
    for index, tensor in enumerate(tensors):
        shape = vector(builder, tensor.shape)
        signature = (
            vector(builder, tensor.signature) if tensor.signature is not None else 0
        )
        name = builder.CreateString(tensor.name)
        quantization = 0
        if tensor.q is not None:
            scales = vector(builder, tensor.q.scales, "float32")
            points = vector(builder, tensor.q.zero_points, "int64")
            tflite.QuantizationParametersStart(builder)
            tflite.QuantizationParametersAddScale(builder, scales)
            tflite.QuantizationParametersAddZeroPoint(builder, points)
            tflite.QuantizationParametersAddQuantizedDimension(builder, tensor.q.axis)
            tflite.QuantizationParametersAddDetailsType(builder, tensor.q.details_type)
            quantization = tflite.QuantizationParametersEnd(builder)
        sparsity = 0
        if tensor.sparse:
            tflite.SparsityParametersStart(builder)
            sparsity = tflite.SparsityParametersEnd(builder)
        tflite.TensorStart(builder)
        tflite.TensorAddShape(builder, shape)
        tflite.TensorAddType(builder, getattr(tflite.TensorType, tensor.dtype))
        tflite.TensorAddBuffer(
            builder,
            buffer_ids[index]
            if tensor.buffer_override is None
            else tensor.buffer_override,
        )
        tflite.TensorAddName(builder, name)
        tflite.TensorAddHasRank(builder, True)
        tflite.TensorAddIsVariable(builder, tensor.variable)
        if signature:
            tflite.TensorAddShapeSignature(builder, signature)
        if quantization:
            tflite.TensorAddQuantization(builder, quantization)
        if sparsity:
            tflite.TensorAddSparsity(builder, sparsity)
        tensor_offsets.append(tflite.TensorEnd(builder))
    code_specs = list(
        dict.fromkeys(
            (
                op.kind,
                VERSIONS.get(op.kind, 1) if op.version is None else op.version,
                op.custom_code,
            )
            for op in nodes
        )
    )
    code_offsets = []
    for kind, ver, custom_code in code_specs:
        custom = builder.CreateString(custom_code) if custom_code is not None else 0
        code = getattr(tflite.BuiltinOperator, kind)
        tflite.OperatorCodeStart(builder)
        tflite.OperatorCodeAddBuiltinCode(builder, code)
        if not modern_code_only:
            tflite.OperatorCodeAddDeprecatedBuiltinCode(builder, min(code, 127))
        tflite.OperatorCodeAddVersion(builder, ver)
        if custom:
            tflite.OperatorCodeAddCustomCode(builder, custom)
        code_offsets.append(tflite.OperatorCodeEnd(builder))
    node_offsets = []
    for op in nodes:
        source_inputs = vector(builder, op.inputs)
        source_outputs = vector(builder, op.outputs)
        options_type, options = build_options(builder, op)
        custom_options = (
            builder.CreateByteVector(op.custom_options) if op.custom_options else 0
        )
        mutating = (
            vector(builder, op.mutating_inputs, "bool") if op.mutating_inputs else 0
        )
        intermediates = vector(builder, op.intermediates) if op.intermediates else 0
        tflite.OperatorStart(builder)
        tflite.OperatorAddOpcodeIndex(
            builder,
            code_specs.index(
                (
                    op.kind,
                    VERSIONS.get(op.kind, 1) if op.version is None else op.version,
                    op.custom_code,
                )
            ),
        )
        tflite.OperatorAddInputs(builder, source_inputs)
        tflite.OperatorAddOutputs(builder, source_outputs)
        tflite.OperatorAddBuiltinOptionsType(
            builder,
            options_type
            if op.options_type_override is None
            else op.options_type_override,
        )
        if options:
            tflite.OperatorAddBuiltinOptions(builder, options)
        if custom_options:
            tflite.OperatorAddCustomOptions(builder, custom_options)
        if mutating:
            tflite.OperatorAddMutatingVariableInputs(builder, mutating)
        if intermediates:
            tflite.OperatorAddIntermediates(builder, intermediates)
        tflite.OperatorAddBuiltinOptions2Type(builder, op.secondary_options)
        node_offsets.append(tflite.OperatorEnd(builder))
    tensors_vector = vector(builder, tensor_offsets, "offset")
    nodes_vector = vector(builder, node_offsets, "offset")
    inputs_vector = vector(builder, inputs)
    outputs_vector = vector(builder, nodes[-1].outputs if outputs is None else outputs)
    name = builder.CreateString("fixture")
    tflite.SubGraphStart(builder)
    tflite.SubGraphAddTensors(builder, tensors_vector)
    tflite.SubGraphAddInputs(builder, inputs_vector)
    tflite.SubGraphAddOutputs(builder, outputs_vector)
    tflite.SubGraphAddOperators(builder, nodes_vector)
    tflite.SubGraphAddName(builder, name)
    subgraph = tflite.SubGraphEnd(builder)
    subgraphs_vector = vector(builder, [subgraph] * subgraphs, "offset")
    codes_vector = vector(builder, code_offsets, "offset")
    buffers_vector = vector(builder, buffers, "offset")
    tflite.ModelStart(builder)
    tflite.ModelAddVersion(builder, schema_version)
    tflite.ModelAddSubgraphs(builder, subgraphs_vector)
    tflite.ModelAddOperatorCodes(builder, codes_vector)
    tflite.ModelAddBuffers(builder, buffers_vector)
    model = tflite.ModelEnd(builder)
    builder.Finish(model, file_identifier=b"TFL3")
    return bytes(builder.Output())
