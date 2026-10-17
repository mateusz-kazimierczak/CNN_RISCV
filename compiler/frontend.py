"""Pinned TFLite FlatBuffer import, with explicit supported-field decoding."""

from __future__ import annotations

import hashlib
import struct
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .ir import (
    AddOptions,
    Buffer,
    Conv2DOptions,
    DepthwiseConv2DOptions,
    FullyConnectedOptions,
    Graph,
    ModelError,
    Node,
    Operand,
    OperatorCode,
    Pool2DOptions,
    Quantization,
    QuantizeOptions,
    ReshapeOptions,
    SoftmaxOptions,
    Tensor,
)
from .validation import INPUT_ROLES, SUPPORTED_VERSIONS, require, validate_graph

DEPENDENCIES = {"tflite": "2.18.0", "flatbuffers": "25.12.19", "numpy": "2.4.3"}

# Schema field order and widths from the pinned generated bindings. Check every
# populated field before access, including vector bounds and otherwise ignored
# future fields. This is intentionally a small supported-schema reader.
TABLE_FIELDS = {
    "Model": ("4", "v4", "v4", "str", "v4", "v4", "v4", "v4"),
    "SubGraph": ("v4", "v4", "v4", "v4", "str", "4"),
    "OperatorCode": ("1", "str", "4", "4"),
    "Tensor": ("v4", "1", "4", "str", "ref", "bool", "ref", "v4", "bool", "v4"),
    "Buffer": ("v1", "8", "8"),
    "QuantizationParameters": ("v4", "v4", "v4", "v8", "1", "ref", "4"),
    "Operator": (
        "4",
        "v4",
        "v4",
        "1",
        "ref",
        "v1",
        "1",
        "v1",
        "v4",
        "8",
        "8",
        "1",
        "ref",
        "4",
    ),
    "Conv2DOptions": ("1", "4", "4", "1", "4", "4", "1"),
    "DepthwiseConv2DOptions": ("1", "4", "4", "4", "1", "4", "4"),
    "Pool2DOptions": ("1", "4", "4", "4", "4", "1"),
    "FullyConnectedOptions": ("1", "1", "bool", "bool", "1"),
    "AddOptions": ("1", "bool"),
    "ReshapeOptions": ("v4",),
    "SoftmaxOptions": ("4",),
    "QuantizeOptions": (),
}


def bindings():
    try:
        for package, expected in DEPENDENCIES.items():
            actual = version(package)
            require(
                actual == expected,
                f"frontend requires {package}=={expected}, found {actual}",
            )
        import tflite

        return tflite
    except (PackageNotFoundError, ModuleNotFoundError) as error:
        raise ModelError(
            "frontend dependencies unavailable; use uv run --python 3.12 "
            "--with-requirements tools/compiler/requirements.txt python -m compiler ..."
        ) from error


def checked_table(obj, kind: str, identity: str) -> None:
    table = obj._tab
    data, position = table.Bytes, table.Pos
    require(0 <= position <= len(data) - 4, f"{identity}: table outside FlatBuffer")
    vtable = position - struct.unpack_from("<i", data, position)[0]
    require(0 <= vtable <= len(data) - 4, f"{identity}: invalid vtable offset")
    size, object_size = struct.unpack_from("<HH", data, vtable)
    require(
        size >= 4
        and size % 2 == 0
        and vtable + size <= len(data)
        and object_size >= 4
        and position + object_size <= len(data),
        f"{identity}: malformed table bounds",
    )
    schema = TABLE_FIELDS[kind]
    for slot in range((size - 4) // 2):
        offset = struct.unpack_from("<H", data, vtable + 4 + 2 * slot)[0]
        if not offset:
            continue
        require(
            slot < len(schema), f"{identity}: unsupported populated {kind} field {slot}"
        )
        field = schema[slot]
        width = (
            4
            if field in ("str", "ref") or field.startswith("v")
            else 1
            if field == "bool"
            else int(field)
        )
        require(
            4 <= offset and offset + width <= object_size,
            f"{identity}: field {slot} exceeds table bounds",
        )
        address = position + offset
        if field == "bool":
            require(
                data[address] in (0, 1), f"{identity}: invalid boolean field {slot}"
            )
        if field in ("str", "ref") or field.startswith("v"):
            relative = struct.unpack_from("<I", data, address)[0]
            target = address + relative
            require(
                relative >= 4 and target + 4 <= len(data),
                f"{identity}: field {slot} offset outside FlatBuffer",
            )
            if field != "ref":
                length = struct.unpack_from("<I", data, target)[0]
                element_width = 1 if field == "str" else int(field[1:])
                end = target + 4 + length * element_width
                require(
                    end <= len(data),
                    f"{identity}: field {slot} vector outside FlatBuffer",
                )
                if field == "str":
                    require(
                        end < len(data) and data[end] == 0,
                        f"{identity}: unterminated FlatBuffer string",
                    )


def enum_value(enum, value: int, identity: str) -> str:
    # The existing inspector's helper works for the uppercase TFLite enums.
    from tools.inspect_tflite import enum_names

    names = enum_names(enum)
    # A few schema enum members, e.g. SHUFFLED4x16INT8, contain lowercase text.
    for name in dir(enum):
        value_of_name = getattr(enum, name)
        if not name.startswith("_") and type(value_of_name) is int:
            names.setdefault(value_of_name, name)
    require(value in names, f"{identity}: unknown enum value {value}")
    return names[value]


def decode_options(tflite, source, kind: str, index: int):
    name = {
        "CONV_2D": "Conv2DOptions",
        "DEPTHWISE_CONV_2D": "DepthwiseConv2DOptions",
        "ADD": "AddOptions",
        "AVERAGE_POOL_2D": "Pool2DOptions",
        "FULLY_CONNECTED": "FullyConnectedOptions",
        "RESHAPE": "ReshapeOptions",
        "SOFTMAX": "SoftmaxOptions",
        "QUANTIZE": "QuantizeOptions",
    }[kind]
    identity = f"node {index} ({kind})"
    table = source.BuiltinOptions()
    if source.BuiltinOptionsType() == tflite.BuiltinOptions.NONE:
        require(table is None, identity + ": NONE option discriminator has a table")
        require(
            kind in ("RESHAPE", "QUANTIZE"),
            identity + ": missing required builtin options",
        )
        return "NONE", ReshapeOptions(None) if kind == "RESHAPE" else QuantizeOptions()
    require(
        source.BuiltinOptionsType() == getattr(tflite.BuiltinOptions, name),
        identity + ": builtin option union discriminator mismatch",
    )
    require(table is not None, identity + ": missing builtin option table")
    options = getattr(tflite, name)()
    options.Init(table.Bytes, table.Pos)
    checked_table(options, name, identity)

    def activation():
        return enum_value(
            tflite.ActivationFunctionType,
            options.FusedActivationFunction(),
            identity + " activation",
        )

    def padding():
        return enum_value(tflite.Padding, options.Padding(), identity + " padding")

    if kind == "CONV_2D":
        result = Conv2DOptions(
            padding(),
            options.StrideH(),
            options.StrideW(),
            options.DilationHFactor(),
            options.DilationWFactor(),
            activation(),
            enum_value(
                tflite.TensorType, options.QuantizedBiasType(), identity + " bias type"
            ),
        )
    elif kind == "DEPTHWISE_CONV_2D":
        result = DepthwiseConv2DOptions(
            padding(),
            options.StrideH(),
            options.StrideW(),
            options.DilationHFactor(),
            options.DilationWFactor(),
            options.DepthMultiplier(),
            activation(),
        )
    elif kind == "ADD":
        result = AddOptions(activation(), options.PotScaleInt16())
    elif kind == "AVERAGE_POOL_2D":
        result = Pool2DOptions(
            padding(),
            options.StrideH(),
            options.StrideW(),
            options.FilterHeight(),
            options.FilterWidth(),
            activation(),
        )
    elif kind == "FULLY_CONNECTED":
        result = FullyConnectedOptions(
            activation(),
            enum_value(
                tflite.FullyConnectedOptionsWeightsFormat,
                options.WeightsFormat(),
                identity + " weight format",
            ),
            options.KeepNumDims(),
            options.AsymmetricQuantizeInputs(),
            enum_value(
                tflite.TensorType, options.QuantizedBiasType(), identity + " bias type"
            ),
        )
    elif kind == "RESHAPE":
        result = ReshapeOptions(
            None
            if options.NewShapeIsNone()
            else tuple(options.NewShape(i) for i in range(options.NewShapeLength()))
        )
    elif kind == "SOFTMAX":
        result = SoftmaxOptions(float(options.Beta()))
    else:
        result = QuantizeOptions()
    return name, result


def import_bytes(data: bytes) -> Graph:
    """Import/validate the small supported subset; public CLI adds the exact-model lock."""
    tflite = bindings()
    data = bytes(data)
    require(
        len(data) >= 8 and data[4:8] == b"TFL3", "missing TFL3 FlatBuffer identifier"
    )
    root = struct.unpack_from("<I", data, 0)[0]
    require(8 <= root <= len(data) - 4, "invalid FlatBuffer root offset")
    try:
        model = tflite.Model.GetRootAsModel(data, 0)
        checked_table(model, "Model", "model")
        require(
            model.Version() == 3, f"unsupported TFLite schema version {model.Version()}"
        )
        require(
            model.SubgraphsLength() == 1, "exactly one static subgraph is supported"
        )
        require(
            model.SignatureDefsLength()
            == model.MetadataLength()
            == model.MetadataBufferLength()
            == 0,
            "model signatures/metadata extensions are outside the supported fixed-model subset",
        )
        buffers = []
        for index in range(model.BuffersLength()):
            source = model.Buffers(index)
            checked_table(source, "Buffer", f"buffer {index}")
            require(
                source.Offset() == source.Size() == 0,
                f"buffer {index}: external buffer payload is unsupported",
            )
            payload = bytes(source.DataAsNumpy()) if source.DataLength() else b""
            buffers.append(Buffer(index, payload))
        codes = []
        for index in range(model.OperatorCodesLength()):
            source = model.OperatorCodes(index)
            checked_table(source, "OperatorCode", f"opcode {index}")
            require(
                source.CustomCode() is None,
                f"opcode {index}: custom operators are unsupported",
            )
            # Match pinned TFLM schema_utils::GetBuiltinCode, including legacy
            # files and modern tables that set only the int32 field. The Python
            # binding's convenience accessor differs for the latter form.
            offset = source._tab.Offset(10)
            raw_code = (
                struct.unpack_from("<i", data, source._tab.Pos + offset)[0]
                if offset
                else 0
            )
            deprecated = source.DeprecatedBuiltinCode()
            require(
                raw_code >= 0 and deprecated >= 0,
                f"opcode {index}: negative builtin code",
            )
            builtin_code = max(raw_code, deprecated)
            name = enum_value(tflite.BuiltinOperator, builtin_code, f"opcode {index}")
            require(
                name in SUPPORTED_VERSIONS
                and source.Version() == SUPPORTED_VERSIONS.get(name),
                f"opcode {index}: unsupported {name} version {source.Version()}",
            )
            codes.append(
                OperatorCode(
                    index, builtin_code, name, source.Version(), raw_code, deprecated
                )
            )
        graph = model.Subgraphs(0)
        checked_table(graph, "SubGraph", "subgraph 0")
        require(
            graph.DebugMetadataIndex() == -1, "subgraph debug metadata is unsupported"
        )
        tensors = []
        for index in range(graph.TensorsLength()):
            source = graph.Tensors(index)
            checked_table(source, "Tensor", f"tensor {index}")
            require(
                not source.IsVariable()
                and source.Sparsity() is None
                and source.VariantTensorsLength() == 0,
                f"tensor {index}: variable, sparse and variant tensors are unsupported",
            )
            require(
                source.Buffer() < len(buffers),
                f"tensor {index}: invalid buffer index {source.Buffer()}",
            )
            q = source.Quantization()
            quantization = None
            if q is not None:
                checked_table(
                    q, "QuantizationParameters", f"tensor {index} quantization"
                )
                require(
                    q.DetailsType() == 0 and q.Details() is None,
                    f"tensor {index}: custom quantization details are unsupported",
                )
                quantization = Quantization(
                    tuple(float(q.Scale(i)) for i in range(q.ScaleLength())),
                    tuple(int(q.ZeroPoint(i)) for i in range(q.ZeroPointLength())),
                    q.QuantizedDimension(),
                    tuple(float(q.Min(i)) for i in range(q.MinLength())),
                    tuple(float(q.Max(i)) for i in range(q.MaxLength())),
                )
            tensors.append(
                Tensor(
                    index=index,
                    subgraph=0,
                    name=(source.Name() or b"").decode("utf-8"),
                    shape=tuple(source.Shape(i) for i in range(source.ShapeLength())),
                    shape_signature=None
                    if source.ShapeSignatureIsNone()
                    else tuple(
                        source.ShapeSignature(i)
                        for i in range(source.ShapeSignatureLength())
                    ),
                    has_rank=source.HasRank(),
                    dtype=enum_value(
                        tflite.TensorType, source.Type(), f"tensor {index}"
                    ),
                    buffer=source.Buffer(),
                    storage="constant" if buffers[source.Buffer()].data else "runtime",
                    quantization=quantization,
                )
            )
        nodes = []
        for index in range(graph.OperatorsLength()):
            source = graph.Operators(index)
            checked_table(source, "Operator", f"node {index}")
            require(
                source.OpcodeIndex() < len(codes),
                f"node {index}: invalid opcode index {source.OpcodeIndex()}",
            )
            code = codes[source.OpcodeIndex()]
            require(
                source.CustomOptionsLength() == 0
                and source.CustomOptionsFormat() == 0
                and source.LargeCustomOptionsOffset()
                == source.LargeCustomOptionsSize()
                == 0,
                f"node {index}: custom operator options are unsupported",
            )
            require(
                source.BuiltinOptions2Type() == 0 and source.BuiltinOptions2() is None,
                f"node {index}: secondary builtin options are unsupported",
            )
            require(
                source.IntermediatesLength()
                == source.MutatingVariableInputsLength()
                == 0,
                f"node {index}: intermediates/mutating variable inputs are unsupported",
            )
            require(
                source.DebugMetadataIndex() == -1,
                f"node {index}: debug metadata is unsupported",
            )
            inputs = tuple(source.Inputs(i) for i in range(source.InputsLength()))
            roles = INPUT_ROLES[code.name]
            require(len(inputs) <= len(roles), f"node {index}: invalid input arity")
            operands = tuple(
                Operand(
                    role,
                    None if slot >= len(inputs) or inputs[slot] == -1 else inputs[slot],
                )
                for slot, role in enumerate(roles)
            )
            options_type, options = decode_options(tflite, source, code.name, index)
            nodes.append(
                Node(
                    index=index,
                    subgraph=0,
                    opcode=code.index,
                    kind=code.name,
                    version=code.version,
                    source_inputs=inputs,
                    inputs=operands,
                    outputs=tuple(
                        source.Outputs(i) for i in range(source.OutputsLength())
                    ),
                    options_type=options_type,
                    options=options,
                )
            )
        imported = Graph(
            model_sha256=hashlib.sha256(data).hexdigest(),
            model_size_bytes=len(data),
            tflite_schema_version=model.Version(),
            description=(model.Description() or b"").decode("utf-8"),
            subgraph=0,
            name=(graph.Name() or b"").decode("utf-8"),
            inputs=tuple(graph.Inputs(i) for i in range(graph.InputsLength())),
            outputs=tuple(graph.Outputs(i) for i in range(graph.OutputsLength())),
            operator_codes=tuple(codes),
            buffers=tuple(buffers),
            tensors=tuple(tensors),
            nodes=tuple(nodes),
        )
        return validate_graph(imported, normalize=True)
    except (
        struct.error,
        IndexError,
        TypeError,
        OverflowError,
        UnicodeError,
        AttributeError,
        ValueError,
    ) as error:
        if isinstance(error, ModelError):
            raise
        raise ModelError(f"malformed TFLite FlatBuffer: {error}") from error


def import_model(path: Path) -> Graph:
    return import_bytes(path.read_bytes())
