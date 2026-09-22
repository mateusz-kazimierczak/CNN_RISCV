#!/usr/bin/env python3
"""Inspect a TFLite model and emit a machine-readable quantization summary.

Run without installing anything into the repository:

    uv run --python 3.12 --with tflite --with numpy \
      python tools/inspect_tflite.py models/efficientnet-lite0-int8.tflite
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

import numpy as np
import tflite


def enum_names(enum: object) -> dict[int, str]:
    return {
        value: name
        for name in dir(enum)
        if name.isupper() and isinstance(value := getattr(enum, name), int)
    }


def flatbuffer_vector(values: object) -> list:
    """Normalize generated FlatBuffer vector accessors, including empty ones."""
    return values.tolist() if hasattr(values, "tolist") else []


def tensor_record(model: object, subgraph: object, index: int, types: dict[int, str]) -> dict:
    tensor = subgraph.Tensors(index)
    quantization = tensor.Quantization()
    return {
        "index": index,
        "name": tensor.Name().decode("utf-8"),
        "shape": tensor.ShapeAsNumpy().tolist(),
        "type": types.get(tensor.Type(), f"UNKNOWN_{tensor.Type()}"),
        "constant": bool(model.Buffers(tensor.Buffer()).DataLength()),
        "scale_count": quantization.ScaleLength() if quantization else 0,
        "zero_point_count": quantization.ZeroPointLength() if quantization else 0,
        "quantized_dimension": quantization.QuantizedDimension() if quantization else None,
        "scales": flatbuffer_vector(quantization.ScaleAsNumpy()) if quantization else [],
        "zero_points": flatbuffer_vector(quantization.ZeroPointAsNumpy()) if quantization else [],
    }


def inspect(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 8 or data[4:8] != b"TFL3":
        raise ValueError(f"{path} does not have the TFL3 FlatBuffer identifier")

    model = tflite.Model.GetRootAsModel(data, 0)
    tensor_types = enum_names(tflite.TensorType)
    builtin_ops = enum_names(tflite.BuiltinOperator)

    tensor_type_counts: collections.Counter[str] = collections.Counter()
    runtime_type_counts: collections.Counter[str] = collections.Counter()
    constant_type_counts: collections.Counter[str] = collections.Counter()
    operator_counts: collections.Counter[str] = collections.Counter()
    operator_versions: dict[str, set[int]] = collections.defaultdict(set)
    float_tensors: list[dict] = []
    weight_tensors: set[int] = set()
    bias_tensors: set[int] = set()
    bias_scale_mismatches: list[dict] = []
    sparse_tensor_count = 0
    macs = 0

    subgraphs = []
    for subgraph_index in range(model.SubgraphsLength()):
        subgraph = model.Subgraphs(subgraph_index)
        tensors = [
            tensor_record(model, subgraph, index, tensor_types)
            for index in range(subgraph.TensorsLength())
        ]
        for tensor in tensors:
            tensor_type_counts[tensor["type"]] += 1
            destination = constant_type_counts if tensor["constant"] else runtime_type_counts
            destination[tensor["type"]] += 1
            if tensor["type"] in {"FLOAT16", "FLOAT32", "FLOAT64"}:
                float_tensors.append(tensor)
        sparse_tensor_count += sum(
            subgraph.Tensors(index).Sparsity() is not None
            for index in range(subgraph.TensorsLength())
        )

        for operator_index in range(subgraph.OperatorsLength()):
            operator = subgraph.Operators(operator_index)
            opcode = model.OperatorCodes(operator.OpcodeIndex())
            name = builtin_ops.get(opcode.BuiltinCode(), f"UNKNOWN_{opcode.BuiltinCode()}")
            operator_counts[name] += 1
            operator_versions[name].add(opcode.Version())

            inputs = [int(index) for index in operator.InputsAsNumpy() if index >= 0]
            outputs = [int(index) for index in operator.OutputsAsNumpy() if index >= 0]
            if name in {"CONV_2D", "DEPTHWISE_CONV_2D", "FULLY_CONNECTED"}:
                weight_tensors.add(inputs[1])
                if len(inputs) > 2:
                    bias_tensors.add(inputs[2])
                    activation_quant = subgraph.Tensors(inputs[0]).Quantization()
                    weight_quant = subgraph.Tensors(inputs[1]).Quantization()
                    bias_quant = subgraph.Tensors(inputs[2]).Quantization()
                    expected_bias_scales = (
                        np.asarray(activation_quant.ScaleAsNumpy())
                        * np.asarray(weight_quant.ScaleAsNumpy())
                    )
                    actual_bias_scales = np.asarray(bias_quant.ScaleAsNumpy())
                    if not np.allclose(
                        expected_bias_scales, actual_bias_scales, rtol=1e-5, atol=0
                    ):
                        bias_scale_mismatches.append(
                            {"subgraph": subgraph_index, "operator": operator_index}
                        )
                weight_shape = tensors[inputs[1]]["shape"]
                weight_elements = int(np.prod(weight_shape))
                if name == "FULLY_CONNECTED":
                    macs += weight_elements
                elif name == "CONV_2D":
                    output_shape = tensors[outputs[0]]["shape"]
                    macs += int(np.prod(output_shape[1:])) * int(np.prod(weight_shape[1:]))
                else:
                    output_shape = tensors[outputs[0]]["shape"]
                    macs += int(np.prod(output_shape[1:])) * int(np.prod(weight_shape[1:3]))

        subgraphs.append(
            {
                "index": subgraph_index,
                "name": (subgraph.Name() or b"").decode("utf-8"),
                "tensor_count": subgraph.TensorsLength(),
                "operator_count": subgraph.OperatorsLength(),
                "inputs": [tensors[int(index)] for index in subgraph.InputsAsNumpy()],
                "outputs": [tensors[int(index)] for index in subgraph.OutputsAsNumpy()],
            }
        )

    main = model.Subgraphs(0)
    main_tensors = [
        tensor_record(model, main, index, tensor_types)
        for index in range(main.TensorsLength())
    ]
    weights = [main_tensors[index] for index in sorted(weight_tensors)]
    biases = [main_tensors[index] for index in sorted(bias_tensors)]
    all_weights_int8 = all(tensor["type"] == "INT8" for tensor in weights)
    all_biases_int32 = all(tensor["type"] == "INT32" for tensor in biases)
    symmetric_weights = all(set(tensor["zero_points"]) <= {0} for tensor in weights)
    per_axis_weight_count = sum(tensor["scale_count"] > 1 for tensor in weights)
    weight_parameter_count = sum(int(np.prod(tensor["shape"])) for tensor in weights)
    bias_parameter_count = sum(int(np.prod(tensor["shape"])) for tensor in biases)

    return {
        "path": str(path),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "flatbuffer_identifier": data[4:8].decode("ascii"),
        "schema_version": model.Version(),
        "description": (model.Description() or b"").decode("utf-8"),
        "subgraph_count": model.SubgraphsLength(),
        "subgraphs": subgraphs,
        "tensor_type_counts": dict(sorted(tensor_type_counts.items())),
        "runtime_tensor_type_counts": dict(sorted(runtime_type_counts.items())),
        "constant_tensor_type_counts": dict(sorted(constant_type_counts.items())),
        "operator_counts": dict(sorted(operator_counts.items())),
        "operator_versions": {
            name: sorted(versions) for name, versions in sorted(operator_versions.items())
        },
        "learned_weight_parameters": weight_parameter_count,
        "learned_bias_parameters": bias_parameter_count,
        "learned_parameter_count": weight_parameter_count + bias_parameter_count,
        "estimated_macs": macs,
        "sparse_tensor_count": sparse_tensor_count,
        "quantization_audit": {
            "float_tensor_count": len(float_tensors),
            "all_operator_weights_int8": all_weights_int8,
            "all_operator_biases_int32": all_biases_int32,
            "all_bias_scales_match_input_times_weight": not bias_scale_mismatches,
            "bias_scale_mismatches": bias_scale_mismatches,
            "all_operator_weights_symmetric_zero_point": symmetric_weights,
            "weight_tensor_count": len(weights),
            "per_axis_weight_tensor_count": per_axis_weight_count,
            "per_tensor_weight_tensor_count": len(weights) - per_axis_weight_count,
            "internal_signed_int8_core": (
                not float_tensors
                and all_weights_int8
                and all_biases_int32
                and runtime_type_counts.get("INT8", 0) > 0
            ),
            "strict_signed_int8_model_io": all(
                tensor["type"] == "INT8"
                for subgraph in subgraphs
                for tensor in subgraph["inputs"] + subgraph["outputs"]
            ),
        },
        "float_tensors": float_tensors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("--output", "-o", type=Path)
    args = parser.parse_args()
    result = inspect(args.model)
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
