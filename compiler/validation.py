"""Strict supported-subset validation, graph edges and static shape inference."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import replace

from .ir import (
    IR_SCHEMA_VERSION,
    OPTION_TYPES,
    REFERENCE_REVISION,
    TYPE_FORMATS,
    Graph,
    ModelError,
    Node,
    Padding,
    Tensor,
)

SUPPORTED_VERSIONS = {
    "CONV_2D": 3,
    "DEPTHWISE_CONV_2D": 3,
    "ADD": 2,
    "AVERAGE_POOL_2D": 2,
    "FULLY_CONNECTED": 4,
    "QUANTIZE": 1,
    "RESHAPE": 1,
    "SOFTMAX": 2,
}
BUILTIN_CODES = {
    "ADD": 0,
    "AVERAGE_POOL_2D": 1,
    "CONV_2D": 3,
    "DEPTHWISE_CONV_2D": 4,
    "FULLY_CONNECTED": 9,
    "RESHAPE": 22,
    "SOFTMAX": 25,
    "QUANTIZE": 114,
}
INPUT_ROLES = {
    "CONV_2D": ("input", "weights", "bias"),
    "DEPTHWISE_CONV_2D": ("input", "weights", "bias"),
    "FULLY_CONNECTED": ("input", "weights", "bias"),
    "ADD": ("lhs", "rhs"),
    "RESHAPE": ("input", "shape"),
    "QUANTIZE": ("input",),
    "SOFTMAX": ("input",),
    "AVERAGE_POOL_2D": ("input",),
}
ACTIVATIONS = {"NONE", "RELU", "RELU6", "RELU_N1_TO_1"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelError(message)


def tensor_quantization(tensor: Tensor) -> None:
    q = tensor.quantization
    if q is None:
        require(
            tensor.dtype == "INT32" and tensor.storage == "constant",
            f"tensor {tensor.index}: missing affine quantization",
        )
        return
    prefix = f"tensor {tensor.index}: "
    require(
        len(q.scales) == len(q.zero_points), prefix + "scale/zero-point count mismatch"
    )
    require(len(q.minimum) == len(q.maximum), prefix + "min/max count mismatch")
    require(
        all(math.isfinite(x) for x in (*q.scales, *q.minimum, *q.maximum)),
        prefix + "non-finite quantization metadata",
    )
    require(all(scale > 0 for scale in q.scales), prefix + "scales must be positive")
    require(len(q.minimum) in (0, 1, len(q.scales)), prefix + "invalid min/max count")
    require(
        all(a <= b for a, b in zip(q.minimum, q.maximum)),
        prefix + "invalid min/max range",
    )
    require(
        type(q.quantized_dimension) is int
        and 0 <= q.quantized_dimension < len(tensor.shape),
        prefix + "invalid quantized dimension",
    )
    if not q.scales:
        require(
            tensor.dtype == "INT32" and tensor.storage == "constant" and not q.minimum,
            prefix + "missing affine quantization",
        )
        return
    require(
        len(q.scales) in (1, tensor.shape[q.quantized_dimension]),
        prefix + "per-axis scale count differs from dimension",
    )
    low, high = {
        "INT8": (-128, 127),
        "UINT8": (0, 255),
        "INT32": (-(1 << 31), (1 << 31) - 1),
    }[tensor.dtype]
    require(
        all(type(point) is int and low <= point <= high for point in q.zero_points),
        prefix + "zero-point outside dtype range",
    )


def per_tensor(tensor: Tensor) -> None:
    require(
        tensor.quantization is not None and len(tensor.quantization.scales) == 1,
        f"tensor {tensor.index}: activation requires per-tensor affine quantization",
    )


def same_quantization(left: Tensor, right: Tensor) -> bool:
    return (
        left.quantization.scales == right.quantization.scales
        and left.quantization.zero_points == right.quantization.zero_points
    )


def window_axis(
    size: int, kernel: int, stride: int, dilation: int, padding: str
) -> tuple[int, int, int]:
    require(
        all(type(value) is int and value > 0 for value in (kernel, stride, dilation)),
        "filter, stride and dilation must be positive integers",
    )
    require(padding in ("SAME", "VALID"), f"unsupported padding {padding}")
    effective = (kernel - 1) * dilation + 1
    output = (
        (size + stride - 1) // stride
        if padding == "SAME"
        else (size - effective) // stride + 1
    )
    require(output > 0, "filter produces a nonpositive output dimension")
    total = max((output - 1) * stride + effective - size, 0) if padding == "SAME" else 0
    return output, total // 2, total - total // 2


def window_shape(
    input_shape: tuple[int, ...],
    output_channels: int,
    kh: int,
    kw: int,
    sh: int,
    sw: int,
    dh: int,
    dw: int,
    mode: str,
) -> tuple[tuple[int, ...], Padding]:
    height, top, bottom = window_axis(input_shape[1], kh, sh, dh, mode)
    width, left, right = window_axis(input_shape[2], kw, sw, dw, mode)
    return (input_shape[0], height, width, output_channels), Padding(
        top, bottom, left, right
    )


def inferred_reshape(shape: tuple[int, ...], elements: int) -> tuple[int, ...]:
    require(
        1 <= len(shape) <= 4
        and all(type(dim) is int and (dim > 0 or dim == -1) for dim in shape),
        "RESHAPE: target must contain positive dimensions and at most one -1",
    )
    require(shape.count(-1) <= 1, "RESHAPE: multiple inferred dimensions")
    fixed = math.prod(dim for dim in shape if dim != -1)
    require(fixed > 0 and elements % fixed == 0, "RESHAPE: incompatible element count")
    result = tuple(elements // fixed if dim == -1 else dim for dim in shape)
    require(math.prod(result) == elements, "RESHAPE: incompatible element count")
    return result


def validate_node(graph: Graph, node: Node, layouts: dict[int, str]) -> Padding | None:
    prefix = f"node {node.index} ({node.kind}): "

    def layout(tensor: Tensor, value: str) -> None:
        previous = layouts.setdefault(tensor.index, value)
        require(
            previous == value,
            prefix + f"incompatible layouts for tensor {tensor.index}",
        )

    def operand(
        name: str, *, rank: int | None = None, constant: bool = False
    ) -> Tensor:
        index = node.input(name)
        require(index is not None, prefix + f"required operand {name} is absent")
        tensor = graph.tensors[index]
        if rank is not None:
            require(len(tensor.shape) == rank, prefix + f"{name} must have rank {rank}")
        if constant:
            require(
                tensor.storage == "constant",
                prefix + f"{name} requires a nonempty constant buffer",
            )
        return tensor

    def activation(tensor: Tensor) -> None:
        require(tensor.dtype == "INT8", prefix + f"tensor {tensor.index} must be INT8")
        per_tensor(tensor)
        require(
            len(tensor.shape) in (2, 4) and tensor.shape[0] == 1,
            prefix + "activations require static batch-one NC or NHWC shapes",
        )
        layout(tensor, "NHWC" if len(tensor.shape) == 4 else "NC")

    def weights_and_bias(
        weights: Tensor,
        inputs: Tensor,
        channels: int,
        axis: int,
        *,
        fully_connected: bool = False,
    ) -> None:
        require(weights.dtype == "INT8", prefix + "weights must be INT8")
        q = weights.quantization
        require(
            q is not None and len(q.scales) in (1, channels),
            prefix + "invalid weight scale count",
        )
        require(
            q.quantized_dimension == axis,
            prefix + f"weight quantized dimension must be {axis}",
        )
        require(
            all(point == 0 for point in q.zero_points),
            prefix + "weights must have symmetric zero-points",
        )
        if fully_connected:
            require(
                len(q.scales) == 1,
                prefix + "per-channel FC is outside this model's supported subset",
            )
        bias_id = node.input("bias")
        if bias_id is None:
            return
        bias = operand("bias", rank=1, constant=True)
        layout(bias, "C")
        require(
            bias.dtype == "INT32" and bias.shape == (channels,),
            prefix + "bias must be INT32 [output_channels]",
        )
        bq = bias.quantization
        require(
            bq is not None
            and bq.quantized_dimension == 0
            and len(bq.scales) == len(q.scales),
            prefix + "bias quantization must match weight channels",
        )
        require(
            all(point == 0 for point in bq.zero_points),
            prefix + "bias zero-points must be zero",
        )
        require(
            all(
                math.isclose(
                    b, inputs.quantization.scales[0] * w, rel_tol=1e-5, abs_tol=0
                )
                for b, w in zip(bq.scales, q.scales)
            ),
            prefix + "bias scales differ from input scale * weight scales",
        )

    output = graph.tensors[node.outputs[0]]
    options = node.options
    if hasattr(options, "fused_activation"):
        require(
            options.fused_activation in ACTIVATIONS,
            prefix + "unsupported fused activation",
        )
    if hasattr(options, "quantized_bias_type"):
        # FLOAT32 is the legacy schema default, not this graph's actual bias dtype.
        require(
            options.quantized_bias_type in ("FLOAT32", "INT32"),
            prefix + "unsupported quantized_bias_type",
        )

    if node.kind in ("CONV_2D", "DEPTHWISE_CONV_2D"):
        inputs = operand("input", rank=4)
        weights = operand("weights", rank=4, constant=True)
        activation(inputs)
        activation(output)
        if node.kind == "CONV_2D":
            channels, kh, kw, depth = weights.shape
            require(
                depth == inputs.shape[3],
                prefix + "grouped or mismatched convolution input channels",
            )
            layout(weights, "OHWI")
            axis = 0
        else:
            require(
                weights.shape[0] == 1,
                prefix + "depthwise weights must have shape [1,H,W,O]",
            )
            require(
                type(options.depth_multiplier) is int and options.depth_multiplier > 0,
                prefix + "depth multiplier must be positive",
            )
            _, kh, kw, channels = weights.shape
            require(
                channels == inputs.shape[3] * options.depth_multiplier,
                prefix + "depth multiplier/filter channels mismatch",
            )
            layout(weights, "1HWO")
            axis = 3
        weights_and_bias(weights, inputs, channels, axis)
        shape, padding = window_shape(
            inputs.shape,
            channels,
            kh,
            kw,
            options.stride_h,
            options.stride_w,
            options.dilation_h,
            options.dilation_w,
            options.padding,
        )
        require(
            output.shape == shape,
            prefix + f"output shape {output.shape} != inferred {shape}",
        )
        return padding
    if node.kind == "ADD":
        left, right = operand("lhs"), operand("rhs")
        for tensor in (left, right, output):
            activation(tensor)
        require(
            left.shape == right.shape == output.shape,
            prefix + "broadcast ADD is unsupported; shapes must match",
        )
        require(
            type(options.pot_scale_int16) is bool,
            prefix + "invalid pot_scale_int16 option",
        )
    elif node.kind == "AVERAGE_POOL_2D":
        inputs = operand("input", rank=4)
        activation(inputs)
        activation(output)
        require(
            same_quantization(inputs, output),
            prefix + "average pool input/output quantization must match",
        )
        shape, padding = window_shape(
            inputs.shape,
            inputs.shape[3],
            options.filter_h,
            options.filter_w,
            options.stride_h,
            options.stride_w,
            1,
            1,
            options.padding,
        )
        require(
            output.shape == shape,
            prefix + f"output shape {output.shape} != inferred {shape}",
        )
        return padding
    elif node.kind == "FULLY_CONNECTED":
        inputs = operand("input", rank=2)
        weights = operand("weights", rank=2, constant=True)
        activation(inputs)
        activation(output)
        require(
            options.weights_format == "DEFAULT"
            and options.keep_num_dims is False
            and options.asymmetric_quantize_inputs is False,
            prefix
            + "only DEFAULT weights, keep_num_dims=false, asymmetric_quantize_inputs=false are supported",
        )
        channels, depth = weights.shape
        require(
            inputs.shape[1] == depth and output.shape == (inputs.shape[0], channels),
            prefix + "FC input/weight/output shape mismatch",
        )
        layout(weights, "OI")
        weights_and_bias(weights, inputs, channels, 0, fully_connected=True)
    elif node.kind == "RESHAPE":
        inputs = operand("input")
        activation(inputs)
        activation(output)
        require(
            inputs.elements == output.elements and same_quantization(inputs, output),
            prefix + "RESHAPE must preserve element count and quantization",
        )
        targets = []
        if node.input("shape") is not None:
            shape_tensor = operand("shape", rank=1, constant=True)
            require(
                shape_tensor.dtype == "INT32", prefix + "shape tensor must be INT32"
            )
            require(
                shape_tensor.quantization is None
                or not shape_tensor.quantization.scales,
                prefix + "shape tensor must not have affine quantization",
            )
            layout(shape_tensor, "SHAPE")
            targets.append(graph.constant_values(shape_tensor.index))
        if options.new_shape is not None:
            targets.append(options.new_shape)
        require(
            bool(targets),
            prefix + "missing constant shape operand and new_shape option",
        )
        for target in targets:
            require(
                inferred_reshape(target, inputs.elements) == output.shape,
                prefix + "constant/option target shape differs from declared output",
            )
    elif node.kind == "SOFTMAX":
        inputs = operand("input", rank=2)
        activation(inputs)
        activation(output)
        require(output.shape == inputs.shape, prefix + "Softmax shape mismatch")
        require(
            math.isfinite(options.beta) and options.beta > 0,
            prefix + "beta must be positive and finite",
        )
        require(
            output.quantization.scales == (1 / 256,)
            and output.quantization.zero_points == (-128,),
            prefix + "INT8 Softmax output requires scale 1/256 and zero-point -128",
        )
    elif node.kind == "QUANTIZE":
        inputs = operand("input")
        require(
            (inputs.dtype, output.dtype) in (("UINT8", "INT8"), ("INT8", "UINT8")),
            prefix + "only this model's UINT8/INT8 boundary conversions are supported",
        )
        for tensor in (inputs, output):
            per_tensor(tensor)
            require(
                len(tensor.shape) in (2, 4) and tensor.shape[0] == 1,
                prefix + "boundary tensor must have static batch-one NC or NHWC shape",
            )
            layout(tensor, "NHWC" if len(tensor.shape) == 4 else "NC")
        delta = -128 if inputs.dtype == "UINT8" else 128
        require(
            inputs.shape == output.shape
            and inputs.quantization.scales == output.quantization.scales
            and output.quantization.zero_points[0]
            == inputs.quantization.zero_points[0] + delta,
            prefix
            + "boundary conversion requires identical shape/scale and a 128-point representation shift",
        )
    return None


def validate_graph(graph: Graph, *, normalize: bool = False) -> Graph:
    """Validate all source metadata; only the importer may fill derived fields."""
    require(
        graph.ir_schema_version == IR_SCHEMA_VERSION
        and graph.tflite_schema_version == 3,
        "unsupported IR or TFLite schema version",
    )
    require(
        graph.byte_order == "little" and graph.reference_revision == REFERENCE_REVISION,
        "unsupported byte order or reference revision",
    )
    require(
        graph.numerical_contract
        == Graph.__dataclass_fields__["numerical_contract"].default,
        "Stage 1 cannot claim prepared integer arithmetic parameters",
    )
    require(
        graph.subgraph == 0
        and bool(graph.nodes)
        and bool(graph.tensors)
        and bool(graph.buffers),
        "expected one nonempty static subgraph",
    )
    require(
        len(graph.model_sha256) == 64
        and all(c in "0123456789abcdef" for c in graph.model_sha256)
        and graph.model_size_bytes >= 8,
        "invalid source model hash/size",
    )
    for index, buffer in enumerate(graph.buffers):
        require(
            buffer.index == index, "buffer IDs must retain original contiguous indices"
        )
    for index, tensor in enumerate(graph.tensors):
        prefix = f"tensor {index}: "
        require(
            tensor.index == index and tensor.subgraph == 0,
            prefix + "invalid original tensor identity",
        )
        require(
            tensor.dtype in TYPE_FORMATS, prefix + f"unsupported dtype {tensor.dtype}"
        )
        require(
            1 <= len(tensor.shape) <= 4
            and all(type(dim) is int and 0 < dim <= 0x7FFFFFFF for dim in tensor.shape),
            prefix + "only positive static shapes of rank 1–4 are supported",
        )
        require(
            tensor.elements <= 0x7FFFFFFF,
            prefix + "element count exceeds TFLM int32 shape arithmetic",
        )
        require(
            tensor.shape_signature is None or tensor.shape_signature == tensor.shape,
            prefix + "dynamic or inconsistent shape signature",
        )
        require(
            type(tensor.buffer) is int and 0 <= tensor.buffer < len(graph.buffers),
            prefix + "invalid buffer index",
        )
        data = graph.buffers[tensor.buffer].data
        require(
            tensor.storage == ("constant" if data else "runtime"),
            prefix + "storage class disagrees with buffer",
        )
        require(
            not data or len(data) == tensor.byte_length,
            prefix
            + f"constant byte length {len(data)} != expected {tensor.byte_length}",
        )
        tensor_quantization(tensor)
    require(
        bool(graph.inputs) and bool(graph.outputs), "missing graph inputs or outputs"
    )
    for label, indices in (("input", graph.inputs), ("output", graph.outputs)):
        require(len(indices) == len(set(indices)), f"duplicate graph {label} tensor")
        for index in indices:
            require(
                type(index) is int and 0 <= index < len(graph.tensors),
                f"invalid graph {label} tensor index {index}",
            )
            require(
                graph.tensors[index].storage == "runtime"
                and graph.tensors[index].dtype in ("INT8", "UINT8"),
                f"graph {label} {index} must be a runtime INT8/UINT8 tensor",
            )
    for index, code in enumerate(graph.operator_codes):
        require(
            code.index == index, "operator code indices must retain source identities"
        )
        require(
            code.name in SUPPORTED_VERSIONS
            and code.version == SUPPORTED_VERSIONS.get(code.name),
            f"opcode {index}: unsupported {code.name} version {code.version}",
        )
        require(
            code.builtin_code == BUILTIN_CODES[code.name],
            f"opcode {index}: builtin code/name mismatch",
        )
        require(
            code.builtin_code_field >= 0
            and 0 <= code.deprecated_builtin_code <= 127
            and code.builtin_code
            == max(code.builtin_code_field, code.deprecated_builtin_code),
            f"opcode {index}: raw builtin code fields disagree with normalized code",
        )

    producers: dict[int, int] = {}
    consumers: dict[int, set[int]] = {
        index: set() for index in range(len(graph.tensors))
    }
    for index, node in enumerate(graph.nodes):
        prefix = f"node {index}: "
        require(
            node.index == index and node.subgraph == 0,
            prefix + "invalid original operator identity",
        )
        require(
            type(node.opcode) is int and 0 <= node.opcode < len(graph.operator_codes),
            prefix + "invalid opcode index",
        )
        code = graph.operator_codes[node.opcode]
        require(
            (node.kind, node.version) == (code.name, code.version),
            prefix + "operator/code identity mismatch",
        )
        require(
            isinstance(node.options, OPTION_TYPES[node.kind]),
            prefix + "options type mismatch",
        )
        expected_type = OPTION_TYPES[node.kind].__name__
        allowed_types = (
            {expected_type, "NONE"}
            if node.kind in ("QUANTIZE", "RESHAPE")
            else {expected_type}
        )
        require(
            node.options_type in allowed_types, prefix + "builtin option union mismatch"
        )
        roles = INPUT_ROLES[node.kind]
        optional = node.kind in (
            "CONV_2D",
            "DEPTHWISE_CONV_2D",
            "FULLY_CONNECTED",
            "RESHAPE",
        )
        allowed_arity = (len(roles) - 1, len(roles)) if optional else (len(roles),)
        require(
            len(node.source_inputs) in allowed_arity, prefix + "invalid input arity"
        )
        normalized_inputs = tuple(
            None if value == -1 else value for value in node.source_inputs
        )
        normalized_inputs += (None,) * (len(roles) - len(normalized_inputs))
        require(
            tuple(operand.name for operand in node.inputs) == roles
            and tuple(operand.tensor for operand in node.inputs) == normalized_inputs,
            prefix + "named inputs disagree with source indices",
        )
        for slot, operand in enumerate(node.inputs):
            if operand.tensor is None:
                require(
                    optional and slot == len(roles) - 1,
                    prefix + f"required input {operand.name} is absent",
                )
                continue
            require(
                type(operand.tensor) is int
                and 0 <= operand.tensor < len(graph.tensors),
                prefix + f"invalid input tensor index {operand.tensor}",
            )
            consumers[operand.tensor].add(index)
        require(len(node.outputs) == 1, prefix + "exactly one output is supported")
        for output in node.outputs:
            require(
                type(output) is int and 0 <= output < len(graph.tensors),
                prefix + f"invalid output tensor index {output}",
            )
            require(
                output not in producers,
                prefix + f"multiple producers for tensor {output}",
            )
            require(
                output not in graph.inputs
                and graph.tensors[output].storage == "runtime",
                prefix + "cannot overwrite a graph input or constant",
            )
            producers[output] = index

    layouts: dict[int, str] = {}
    normalized_nodes = []
    for node in graph.nodes:
        try:
            padding = validate_node(graph, node, layouts)
        except ModelError as error:
            if str(error).startswith("node "):
                raise
            raise ModelError(f"node {node.index} ({node.kind}): {error}") from error
        if not normalize:
            require(
                node.padding == padding, f"node {node.index}: inferred padding mismatch"
            )
        normalized_nodes.append(replace(node, padding=padding))

    normalized_tensors = []
    for tensor in graph.tensors:
        producer = producers.get(tensor.index)
        uses = tuple(sorted(consumers[tensor.index]))
        if tensor.storage == "runtime" and tensor.index not in graph.inputs:
            require(
                producer is not None,
                f"tensor {tensor.index}: runtime tensor has no producer (missing constant buffer?)",
            )
        if producer is not None:
            require(
                all(consumer > producer for consumer in uses),
                f"tensor {tensor.index}: cyclic or non-topological producer/consumer edge",
            )
        inferred_layout = layouts.get(tensor.index, "ROW_MAJOR")
        if not normalize:
            require(
                (tensor.producer, tensor.consumers, tensor.layout)
                == (producer, uses, inferred_layout),
                f"tensor {tensor.index}: derived producer/consumer/layout metadata mismatch",
            )
        normalized_tensors.append(
            replace(tensor, producer=producer, consumers=uses, layout=inferred_layout)
        )
    return replace(
        graph, nodes=tuple(normalized_nodes), tensors=tuple(normalized_tensors)
    )


def validate_project_model(graph: Graph, audit: dict) -> None:
    """The CLI deliberately accepts only the frozen project model, not arbitrary ML."""
    validate_graph(graph)
    require(
        graph.model_sha256 == audit["sha256"]
        and graph.model_size_bytes == audit["size_bytes"],
        "model hash/size differs from the tracked EfficientNet-Lite0 audit",
    )
    summary = audit["subgraphs"][0]
    require(
        audit["subgraph_count"] == 1
        and len(graph.nodes) == summary["operator_count"]
        and len(graph.tensors) == summary["tensor_count"],
        "model graph counts differ from tracked audit",
    )
    require(
        dict(Counter(node.kind for node in graph.nodes)) == audit["operator_counts"],
        "operator inventory differs from tracked audit",
    )
    versions = {
        name: sorted({node.version for node in graph.nodes if node.kind == name})
        for name in SUPPORTED_VERSIONS
    }
    require(
        versions == audit["operator_versions"],
        "operator versions differ from tracked audit",
    )
    require(
        dict(Counter(tensor.dtype for tensor in graph.tensors))
        == audit["tensor_type_counts"],
        "tensor dtype counts differ from tracked audit",
    )
    for ids, expected in (
        (graph.inputs, summary["inputs"]),
        (graph.outputs, summary["outputs"]),
    ):
        require(
            list(ids) == [item["index"] for item in expected],
            "public I/O tensor identities differ from audit",
        )
        for index, item in zip(ids, expected):
            tensor = graph.tensors[index]
            require(
                (list(tensor.shape), tensor.dtype) == (item["shape"], item["type"])
                and list(tensor.quantization.scales) == item["scales"]
                and list(tensor.quantization.zero_points) == item["zero_points"],
                f"tensor {index}: public I/O contract differs from audit",
            )
