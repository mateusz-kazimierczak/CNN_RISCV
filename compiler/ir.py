"""Typed, lossless constants and static graph metadata; no kernel or memory plans."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import asdict, dataclass, replace
from typing import ClassVar

IR_SCHEMA_VERSION = 1
REFERENCE_REVISION = "9f638f18154dff868e7053572f089be845b2fbdf"
TYPE_FORMATS = {"INT8": ("b", 1), "UINT8": ("B", 1), "INT32": ("i", 4)}


class ModelError(ValueError):
    """An unsupported or inconsistent model, with its original source identity."""


@dataclass(frozen=True)
class Quantization:
    scales: tuple[float, ...]
    zero_points: tuple[int, ...]
    quantized_dimension: int
    minimum: tuple[float, ...] = ()
    maximum: tuple[float, ...] = ()


@dataclass(frozen=True)
class Buffer:
    index: int
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class Tensor:
    index: int
    subgraph: int
    name: str
    shape: tuple[int, ...]
    shape_signature: tuple[int, ...] | None
    has_rank: bool
    dtype: str
    buffer: int
    storage: str
    quantization: Quantization | None
    layout: str = "UNASSIGNED"
    producer: int | None = None
    consumers: tuple[int, ...] = ()

    @property
    def elements(self) -> int:
        return math.prod(self.shape)

    @property
    def byte_length(self) -> int:
        return self.elements * TYPE_FORMATS[self.dtype][1]


@dataclass(frozen=True)
class OperatorCode:
    index: int
    builtin_code: int
    name: str
    version: int
    builtin_code_field: int
    deprecated_builtin_code: int


@dataclass(frozen=True)
class Conv2DOptions:
    padding: str
    stride_h: int
    stride_w: int
    dilation_h: int
    dilation_w: int
    fused_activation: str
    quantized_bias_type: str


@dataclass(frozen=True)
class DepthwiseConv2DOptions:
    padding: str
    stride_h: int
    stride_w: int
    dilation_h: int
    dilation_w: int
    depth_multiplier: int
    fused_activation: str


@dataclass(frozen=True)
class AddOptions:
    fused_activation: str
    pot_scale_int16: bool


@dataclass(frozen=True)
class Pool2DOptions:
    padding: str
    stride_h: int
    stride_w: int
    filter_h: int
    filter_w: int
    fused_activation: str


@dataclass(frozen=True)
class FullyConnectedOptions:
    fused_activation: str
    weights_format: str
    keep_num_dims: bool
    asymmetric_quantize_inputs: bool
    quantized_bias_type: str


@dataclass(frozen=True)
class ReshapeOptions:
    new_shape: tuple[int, ...] | None


@dataclass(frozen=True)
class SoftmaxOptions:
    beta: float


@dataclass(frozen=True)
class QuantizeOptions:
    """Stateless representation conversion; no builtin options in this model."""


Options = (
    Conv2DOptions
    | DepthwiseConv2DOptions
    | AddOptions
    | Pool2DOptions
    | FullyConnectedOptions
    | ReshapeOptions
    | SoftmaxOptions
    | QuantizeOptions
)
OPTION_TYPES = {
    "CONV_2D": Conv2DOptions,
    "DEPTHWISE_CONV_2D": DepthwiseConv2DOptions,
    "ADD": AddOptions,
    "AVERAGE_POOL_2D": Pool2DOptions,
    "FULLY_CONNECTED": FullyConnectedOptions,
    "RESHAPE": ReshapeOptions,
    "SOFTMAX": SoftmaxOptions,
    "QUANTIZE": QuantizeOptions,
}


@dataclass(frozen=True)
class Operand:
    name: str
    tensor: int | None


@dataclass(frozen=True)
class Padding:
    top: int
    bottom: int
    left: int
    right: int


@dataclass(frozen=True)
class Node:
    index: int
    subgraph: int
    opcode: int
    kind: str
    version: int
    source_inputs: tuple[int, ...]
    inputs: tuple[Operand, ...]
    outputs: tuple[int, ...]
    options_type: str
    options: Options
    padding: Padding | None = None

    def input(self, name: str) -> int | None:
        return next(operand.tensor for operand in self.inputs if operand.name == name)


@dataclass(frozen=True)
class Graph:
    model_sha256: str
    model_size_bytes: int
    tflite_schema_version: int
    description: str
    subgraph: int
    name: str
    inputs: tuple[int, ...]
    outputs: tuple[int, ...]
    operator_codes: tuple[OperatorCode, ...]
    buffers: tuple[Buffer, ...]
    tensors: tuple[Tensor, ...]
    nodes: tuple[Node, ...]
    ir_schema_version: int = IR_SCHEMA_VERSION
    reference_revision: str = REFERENCE_REVISION
    byte_order: str = "little"
    numerical_contract: str = "pinned_tflm; prepared integer parameters pending Stage 2"

    CAPABILITIES: ClassVar[dict[str, bool]] = {
        "static_graph": True,
        "constant_bytes": True,
        "validated_shapes_and_quantization_metadata": True,
        "prepared_parameters": False,
        "memory_plan": False,
        "inference_codegen": False,
    }

    def constant_values(self, tensor_index: int) -> tuple[int, ...]:
        tensor = self.tensors[tensor_index]
        if tensor.storage != "constant":
            raise ModelError(f"tensor {tensor_index}: not a constant")
        code, width = TYPE_FORMATS[tensor.dtype]
        data = self.buffers[tensor.buffer].data
        if len(data) != tensor.byte_length or len(data) % width:
            raise ModelError(f"tensor {tensor_index}: invalid constant byte length")
        return tuple(value[0] for value in struct.iter_unpack("<" + code, data))

    def to_dict(self) -> dict:
        result = asdict(replace(self, buffers=()))
        result["buffers"] = [
            {
                "index": buffer.index,
                "byte_length": len(buffer.data),
                "sha256": buffer.sha256,
                "data_hex": buffer.data.hex(),
            }
            for buffer in self.buffers
        ]
        result["tensors"] = [
            {
                **asdict(tensor),
                "byte_length": tensor.byte_length,
                "buffer_byte_length": len(self.buffers[tensor.buffer].data),
            }
            for tensor in self.tensors
        ]
        result["capabilities"] = dict(self.CAPABILITIES)
        return result

    def to_json(self) -> str:
        return (
            json.dumps(self.to_dict(), sort_keys=True, indent=2, allow_nan=False) + "\n"
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    @classmethod
    def from_json(cls, text: str) -> Graph:
        from .validation import validate_graph

        try:
            data = json.loads(text)
            if data.pop("capabilities") != cls.CAPABILITIES:
                raise ModelError("IR capability claims differ from the Stage 1 schema")
            buffers = []
            for record in data.pop("buffers"):
                payload = bytes.fromhex(record["data_hex"])
                buffer = Buffer(index=record["index"], data=payload)
                if (
                    len(payload) != record["byte_length"]
                    or buffer.sha256 != record["sha256"]
                ):
                    raise ModelError(
                        f"buffer {buffer.index}: serialized data/hash mismatch"
                    )
                if set(record) != {"index", "data_hex", "sha256", "byte_length"}:
                    raise ModelError(
                        f"buffer {buffer.index}: unknown serialized fields"
                    )
                buffers.append(buffer)
            tensors = []
            lengths = []
            for record in data.pop("tensors"):
                lengths.append(
                    (record.pop("byte_length"), record.pop("buffer_byte_length"))
                )
                for key in ("shape", "consumers"):
                    record[key] = tuple(record[key])
                signature = record["shape_signature"]
                record["shape_signature"] = (
                    None if signature is None else tuple(signature)
                )
                quantization = record["quantization"]
                if quantization is not None:
                    record["quantization"] = Quantization(
                        **{
                            key: tuple(value) if isinstance(value, list) else value
                            for key, value in quantization.items()
                        }
                    )
                tensors.append(Tensor(**record))
            nodes = []
            for record in data.pop("nodes"):
                options = record["options"]
                if record["kind"] == "RESHAPE" and options["new_shape"] is not None:
                    options["new_shape"] = tuple(options["new_shape"])
                record["options"] = OPTION_TYPES[record["kind"]](**options)
                record["inputs"] = tuple(
                    Operand(**operand) for operand in record["inputs"]
                )
                for key in ("source_inputs", "outputs"):
                    record[key] = tuple(record[key])
                if record["padding"] is not None:
                    record["padding"] = Padding(**record["padding"])
                nodes.append(Node(**record))
            codes = tuple(
                OperatorCode(**record) for record in data.pop("operator_codes")
            )
            graph = cls(
                **{
                    **data,
                    "inputs": tuple(data["inputs"]),
                    "outputs": tuple(data["outputs"]),
                },
                buffers=tuple(buffers),
                tensors=tuple(tensors),
                nodes=tuple(nodes),
                operator_codes=codes,
            )
            validate_graph(graph)
            for tensor, (logical, stored) in zip(graph.tensors, lengths):
                if (tensor.byte_length, len(graph.buffers[tensor.buffer].data)) != (
                    logical,
                    stored,
                ):
                    raise ModelError(
                        f"tensor {tensor.index}: serialized byte length mismatch"
                    )
            return graph
        except (KeyError, TypeError, ValueError, IndexError) as error:
            if isinstance(error, ModelError):
                raise
            raise ModelError(f"invalid serialized graph IR: {error}") from error
