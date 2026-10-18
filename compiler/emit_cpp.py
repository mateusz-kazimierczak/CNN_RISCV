"""Deterministic C++17 emission from validated arithmetic and memory plans."""

from __future__ import annotations

import hashlib
import math
import subprocess
from pathlib import Path

from .execution_plan import make_execution_plan
from .project_runtime import runtime_mode
from .requantization import policy_arguments
from .xrequant import OUTLINE_CHOICE, ADD64_CHOICE
from .depthwise import ZERO as DW_ZERO, BANK as DW_BANK
from .xpostinc import POINTWISE as POSTINC_POINTWISE, DEPTHWISE as POSTINC_DEPTHWISE
from .kernel_plan import (
    STEM_UNROLL_CHOICE,
    XQMAC8_ACCUMULATOR_CHOICE,
    depthwise_filter_size,
    parameter_values,
    pointwise_block_size,
    pointwise_pixels,
    uses_stem_unroll,
)
from .lowering import LoweredModel, validate_lowered_model
from .memory_plan import canonical

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Path(__file__).parent / "templates"


def _values(values, width=24):
    return "\n".join(
        "  " + ", ".join(str(x) for x in values[i : i + width]) + ","
        for i in range(0, len(values), width)
    )


def _constants(model: LoweredModel):
    graph, memory = model.graph, model.memory
    fields = []
    for t in memory.tensors:
        if t.section == ".rodata":
            fields.append(
                (
                    t.offset,
                    f"t{t.tensor}",
                    {"INT32": "int32_t", "INT8": "int8_t", "UINT8": "uint8_t"}[
                        graph.tensors[t.tensor].dtype
                    ],
                    graph.constant_values(t.tensor),
                )
            )
    for p, node, contract in zip(
        memory.parameters, model.prepared.nodes, model.contracts.nodes
    ):
        if not p.size_bytes:
            continue
        payload = parameter_values(node, contract)
        values = []
        for key, offset, _ in p.fields:
            values.extend([0] * (offset // 4 - len(values)))
            v = payload[key]
            values.extend(v if isinstance(v, list) else [v])
        fields.append((p.offset, f"p{p.node}", "int32_t", tuple(values)))
    declarations = [
        "#pragma once",
        "#include <cstddef>",
        "#include <cstdint>",
        f"struct alignas({memory.rodata_alignment}) A0Constants {{",
    ]
    initializers = []
    checks = []
    cursor = 0
    for offset, name, dtype, values in sorted(fields):
        if offset > cursor:
            declarations.append(f"  uint8_t pad_{cursor}[{offset - cursor}];")
            initializers.append("  {},")
        declarations.append(f"  {dtype} {name}[{len(values)}];")
        checks.append(
            f'static_assert(offsetof(A0Constants, {name}) == {offset}, "planned {name} address");'
        )
        initializers.extend(
            [
                f"  // {name}: planned .rodata offset {offset}",
                "  {",
                _values(values),
                "  },",
            ]
        )
        cursor = offset + len(values) * (4 if dtype == "int32_t" else 1)
    declarations.extend(
        [
            "};",
            "extern const A0Constants a0_constants;",
            *checks,
            f'static_assert(sizeof(A0Constants) == {memory.rodata_bytes}, "planned constant size");',
            f'static_assert(alignof(A0Constants) >= {memory.rodata_alignment}, "planned constant alignment");',
        ]
    )
    return (
        "\n".join(declarations) + "\n",
        '#include "constants.h"\nconst A0Constants a0_constants = {\n'
        + "\n".join(initializers)
        + "\n};\n",
    )


def _kernel_call(name, template_arguments, operands, *, returns_status=False):
    """Format C++ without introducing locals or changing expression order.

    Labels are comments, so they remain readable in saved source without
    adding runtime instructions or another layer of generated identifiers.
    """
    prefix = "  return " if returns_status else "  "
    if template_arguments:
        lines = [f"{prefix}{name}<"]
        for index, (label, value) in enumerate(template_arguments):
            comma = "," if index + 1 < len(template_arguments) else ""
            lines.append(f"      /* {label} */ {value}{comma}")
        lines.append("  >(")
    else:
        lines = [f"{prefix}{name}("]
    for index, (label, value) in enumerate(operands):
        comma = "," if index + 1 < len(operands) else ""
        lines.append(f"      {value}{comma}  // {label}")
    lines.append("  );")
    return "\n".join(lines)


def _named_arguments(names, values):
    return tuple(zip(names.split(), values, strict=True))


def _project_call(model, node, selection, tensor, parameter):
    """Emit the already validated project selection; do not select kernels here."""
    geometry = selection.geometry
    parameters = dict(selection.scalar_parameters)
    output_tensor = node.outputs[0]
    output = (f"output t{output_tensor}", tensor(output_tensor))

    def input_operand(role="input"):
        index = node.input(role)
        return (f"{role} t{index}", tensor(index))

    def template(name, arguments, operands):
        return _kernel_call(f"arch_project::{name}", arguments, operands)

    if node.kind == "QUANTIZE":
        source = model.graph.tensors[node.input("input")]
        target = model.graph.tensors[output_tensor]
        input_type, output_type = (
            "uint8_t" if item.dtype == "UINT8" else "int8_t"
            for item in (source, target)
        )
        arguments = _named_arguments(
            "Input Output ElementCount OutputMultiplier OutputShift InputZeroPoint OutputZeroPoint",
            (
                input_type,
                output_type,
                source.elements,
                parameters["requantize_output_multiplier"],
                parameters["requantize_output_shift"],
                parameters["input_zero_point"],
                parameters["output_zero_point"],
            ),
        )
        return template(
            "boundary",
            arguments,
            (
                (
                    f"input t{source.index}",
                    f"reinterpret_cast<const {input_type}*>({tensor(source.index)})",
                ),
                (output[0], f"reinterpret_cast<{output_type}*>({output[1]})"),
            ),
        )
    if node.kind == "ADD":
        scalar_names = (
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
        arguments = _named_arguments(
            "ElementCount LhsOffset RhsOffset OutputOffset LhsMultiplier RhsMultiplier "
            "OutputMultiplier LhsShift RhsShift OutputShift LeftShift ActivationMin ActivationMax",
            (
                model.graph.tensors[output_tensor].elements,
                *(parameters[key] for key in scalar_names),
            ),
        )
        if selection.requantization_backend == "xrequant_v1":
            arguments = (
                *arguments,
                (
                    "Scaling",
                    "arch_project::XRequantization64"
                    if ADD64_CHOICE in selection.choices
                    else "arch_project::XRequantization",
                ),
            )
            if ADD64_CHOICE in selection.choices:
                arguments += (("Accumulator", "int64_t"),)
        return template(
            "add", arguments, (input_operand("lhs"), input_operand("rhs"), output)
        )
    if node.kind == "AVERAGE_POOL_2D":
        arguments = _named_arguments(
            "Batches Pixels Channels ActivationMin ActivationMax",
            (
                geometry.input_shape[0],
                geometry.input_shape[1] * geometry.input_shape[2],
                geometry.input_shape[3],
                parameters["activation_min"],
                parameters["activation_max"],
            ),
        )
        return template("global_average", arguments, (input_operand(), output))
    if node.kind in ("CONV_2D", "FULLY_CONNECTED"):
        bias = node.input("bias")
        operands = (
            input_operand(),
            input_operand("weights"),
            (
                f"original bias t{bias}" if bias is not None else "no bias",
                "nullptr" if bias is None else tensor(bias),
            ),
        )
        offsets = (-parameters["input_zero_point"], parameters["output_zero_point"])
        activation = (
            parameters["output_activation_min"],
            parameters["output_activation_max"],
        )
        if node.kind == "CONV_2D":
            arguments = _named_arguments(
                "InputHeight InputWidth OutputChannels OutputHeight OutputWidth PaddingTop PaddingLeft "
                "InputOffset OutputOffset ActivationMin ActivationMax",
                (
                    *geometry.input_shape[1:3],
                    geometry.output_shape[3],
                    *geometry.output_shape[1:3],
                    geometry.padding[0],
                    geometry.padding[2],
                    *offsets,
                    *activation,
                ),
            )
            return template(
                "stem_rgb",
                (*arguments, *policy_arguments(selection)),
                (
                    *operands,
                    ("prepared per-channel multipliers", parameter("multipliers")),
                    ("prepared per-channel shifts", parameter("shifts")),
                    output,
                ),
            )
        batches = (
            model.graph.tensors[output_tensor].elements // geometry.output_shape[-1]
        )
        arguments = _named_arguments(
            "Batches InputChannels OutputChannels InputOffset OutputOffset OutputMultiplier OutputShift ActivationMin ActivationMax",
            (
                batches,
                geometry.reduction_depth,
                geometry.output_shape[-1],
                *offsets,
                parameters["output_multiplier"],
                parameters["output_shift"],
                *activation,
            ),
        )
        if selection.requantization_backend == "xrequant_v1":
            arguments = (
                *arguments,
                ("Requantization", "arch_project::XRequantization"),
            )
        return template("fully_connected", arguments, (*operands, output))
    if node.kind == "SOFTMAX":
        return "  int32_t sum;\n  int exponent;\n" + _kernel_call(
            "arch_project::numeric::softmax",
            (),
            (
                input_operand(),
                ("depth", geometry.input_shape[-1]),
                ("prepared input multiplier", parameters["input_multiplier"]),
                ("prepared input left shift", parameters["input_left_shift"]),
                ("minimum included input difference", parameters["diff_min"]),
                output,
                ("checked Q12.19 sum (diagnostic)", "&sum"),
                ("normalization exponent (diagnostic)", "&exponent"),
            ),
            returns_status=True,
        )
    raise ValueError(f"unsupported project emission: {node.kind}")


def _node_code(model: LoweredModel, node):
    graph, prepared, memory = (
        model.graph,
        model.prepared.nodes[node.index],
        model.memory,
    )
    selection = model.kernels.nodes[node.index]
    p = parameter_values(prepared, selection.memory)
    scalars = dict(selection.scalar_parameters)
    codegen = "B1_STEM_UNROLL " if STEM_UNROLL_CHOICE in selection.choices else ""
    lines = [
        f'extern "C" A0_NOINLINE {codegen}int a0_node_{node.index:02d}() {{',
        "  A0_NODE_ENTRY();",
    ]
    if model.kernels.configuration in ("B1", "X1", "X2", "X3", "X4"):
        lines.append(
            f"  // Node {node.index}: {node.kind}; {selection.implementation}."
        )
        for operand in node.inputs:
            if operand.tensor is not None:
                item = graph.tensors[operand.tensor]
                shape_text = ", ".join(str(value) for value in item.shape)
                lines.append(
                    f"  // {operand.name}: t{item.index}, {item.dtype} {item.layout} [{shape_text}]."
                )
        for index in node.outputs:
            item = graph.tensors[index]
            shape_text = ", ".join(str(value) for value in item.shape)
            lines.append(
                f"  // output: t{item.index}, {item.dtype} {item.layout} [{shape_text}]."
            )

    def tensor(index):
        t = graph.tensors[index]
        if t.storage == "constant":
            return f"a0_constants.t{index}"
        offset = memory.tensors[index].offset
        return f"(arena.data + {offset})"

    def shape(index):
        return f"a0_static_shape<{len(graph.tensors[index].shape)}>(dims_{index})"

    def parameter(key):
        if selection.requantization_backend == "xrequant_v1":
            if key == "shifts":
                return "nullptr"
            if key == "multipliers":
                key = "xrequant_descriptors"
        if isinstance(p[key], list):
            offset = next(
                offset
                for name, offset, _ in memory.parameters[node.index].fields
                if name == key
            )
            return f"(a0_constants.p{node.index} + {offset // 4})"
        return f"({scalars[key]})"

    def fields(fields):
        for key, value in fields.items():
            lines.append(f"  params.{key} = {value};")

    output = node.outputs[0]
    if selection.implementation.startswith("project/") and node.kind != "RESHAPE":
        lines.append(_project_call(model, node, selection, tensor, parameter))
        if node.kind != "SOFTMAX":
            lines.append("  return 0;")
        return "\n".join([*lines, "}"]) + "\n"
    if node.kind == "QUANTIZE":
        source = node.input("input")
        a = (
            f"reinterpret_cast<const uint8_t*>({tensor(source)})"
            if graph.tensors[source].dtype == "UINT8"
            else tensor(source)
        )
        b = (
            f"reinterpret_cast<uint8_t*>({tensor(output)})"
            if graph.tensors[output].dtype == "UINT8"
            else tensor(output)
        )
        lines.append(
            f"  tflite::reference_ops::Requantize({a}, {graph.tensors[source].elements}, {parameter('requantize_output_multiplier')}, {parameter('requantize_output_shift')}, {parameter('input_zero_point')}, {parameter('output_zero_point')}, {b});"
        )
    elif pointwise_block_size(selection):
        geometry = selection.geometry
        pixels = graph.tensors[output].elements // geometry.output_shape[-1]
        arguments = list(
            _named_arguments(
                "Pixels InputChannels OutputChannels OutputOffset ActivationMin ActivationMax",
                (
                    pixels,
                    geometry.input_shape[-1],
                    geometry.output_shape[-1],
                    scalars["output_zero_point"],
                    scalars["output_activation_min"],
                    scalars["output_activation_max"],
                ),
            )
        )
        block = pointwise_block_size(selection)
        call = "pointwise_dot8" if block == 1 else "pointwise_dot8_blocked"
        spatial = pointwise_pixels(selection) == 2
        if spatial:
            call = "pointwise_dot8_spatial2"
        if block != 1:
            arguments.append(("Block", block))
            if policy_arguments(selection):
                arguments.append(
                    (
                        "Reduction",
                        (
                            "arch_project::ScalarDot8SpatialBlock"
                            if spatial
                            else "arch_project::ScalarDot8Block"
                        ),
                    )
                )
        if selection.reduction_backend.startswith("xqmac8"):
            # Prove alignment from actual unchanged storage placement and strides,
            # rather than upgrading a memory contract with alignment=1.
            def packed_alignment(role):
                item = memory.tensors[node.input(role)]
                base = (
                    memory.rodata_alignment
                    if role == "weights"
                    else memory.arena_alignment
                )
                return math.gcd(8, base, item.offset, geometry.input_shape[-1])

            alignment_arguments = (
                f"{packed_alignment('input')}, {packed_alignment('weights')}"
            )
            if XQMAC8_ACCUMULATOR_CHOICE in selection.choices:
                alignment_arguments += ", 64"
            reduction = (
                "Qmac8SpatialBlock"
                if spatial
                else "Qmac8Block"
                if block != 1
                else "Qmac8Single"
            )
            if POSTINC_POINTWISE in selection.choices:
                reduction = (
                    "Qmac8PostincSpatialBlock" if spatial else "Qmac8PostincBlock"
                )
            arguments = [(k, v) for k, v in arguments if k != "Reduction"]
            if block != 1:
                arguments.append(
                    ("Reduction", f"arch_project::{reduction}<{alignment_arguments}>")
                )
            # The single-output template appends Reduction after Requantization.
            if block == 1:
                arguments.extend(
                    policy_arguments(selection)
                    or (("Requantization", "arch_project::DefaultRequantization"),)
                )
                arguments.append(
                    ("Reduction", f"arch_project::{reduction}<{alignment_arguments}>")
                )
        if not (selection.reduction_backend.startswith("xqmac8") and block == 1):
            arguments.extend(policy_arguments(selection))
        if POSTINC_POINTWISE in selection.choices:
            arguments.append(("PostIncrement", "true"))
        lines.append(
            _kernel_call(
                f"arch_project::{call}",
                arguments,
                (
                    (f"input t{node.input('input')}", tensor(node.input("input"))),
                    (
                        f"OHWI weights t{node.input('weights')}",
                        tensor(node.input("weights")),
                    ),
                    ("prepared corrected biases", parameter("corrected_biases")),
                    ("prepared per-channel multipliers", parameter("multipliers")),
                    ("prepared per-channel shifts", parameter("shifts")),
                    (f"output t{output}", tensor(output)),
                ),
            )
        )
    elif depthwise_filter_size(selection):
        geometry = selection.geometry
        arguments = _named_arguments(
            "Batches InputHeight InputWidth Channels OutputHeight OutputWidth FilterSize "
            "StrideHeight StrideWidth PaddingTop PaddingLeft InputOffset OutputOffset ActivationMin ActivationMax",
            (
                *geometry.input_shape,
                *geometry.output_shape[1:3],
                depthwise_filter_size(selection),
                *geometry.stride,
                geometry.padding[0],
                geometry.padding[2],
                -scalars["input_zero_point"],
                scalars["output_zero_point"],
                scalars["output_activation_min"],
                scalars["output_activation_max"],
            ),
        )
        bias = node.input("bias")
        if DW_ZERO in selection.choices:
            arguments = [(k, 0 if k == "InputOffset" else v) for k, v in arguments]
        arguments = (*arguments, *policy_arguments(selection))
        call = "arch_project::depthwise_fixed"
        if DW_BANK in selection.choices:
            call = "arch_project::depthwise_bank8"

            def alignment_for(role):
                t = memory.tensors[node.input(role)]
                base = (
                    memory.rodata_alignment
                    if role == "weights"
                    else memory.arena_alignment
                )
                return math.gcd(8, base, t.offset, geometry.input_shape[-1])

            arguments += (
                ("InputAlignment", alignment_for("input")),
                ("WeightAlignment", alignment_for("weights")),
            )
        elif DW_ZERO in selection.choices:
            call = "arch_project::depthwise_corrected"
            arguments += (
                (
                    "OutlinePixel",
                    "true" if OUTLINE_CHOICE in selection.choices else "false",
                ),
                (
                    "PostIncrement",
                    "true" if POSTINC_DEPTHWISE in selection.choices else "false",
                ),
                ("CorrectedBiases", "true"),
            )
        elif POSTINC_DEPTHWISE in selection.choices:
            arguments += (
                (
                    "OutlinePixel",
                    "true" if OUTLINE_CHOICE in selection.choices else "false",
                ),
                ("PostIncrement", "true"),
            )
        elif OUTLINE_CHOICE in selection.choices:
            arguments += (("OutlinePixel", "true"),)
        lines.append(
            _kernel_call(
                call,
                arguments,
                (
                    (f"input t{node.input('input')}", tensor(node.input("input"))),
                    (
                        f"1HWO weights t{node.input('weights')}",
                        tensor(node.input("weights")),
                    ),
                    (
                        "region-specific corrected biases"
                        if DW_ZERO in selection.choices
                        else "original biases; border taps keep the input offset",
                        parameter("depthwise_biases")
                        if DW_ZERO in selection.choices
                        else "nullptr"
                        if bias is None
                        else tensor(bias),
                    ),
                    ("prepared per-channel multipliers", parameter("multipliers")),
                    ("prepared per-channel shifts", parameter("shifts")),
                    (f"output t{output}", tensor(output)),
                    *(
                        (
                            (
                                "correction region per output pixel",
                                parameter("depthwise_regions"),
                            ),
                        )
                        if DW_ZERO in selection.choices
                        else ()
                    ),
                ),
            )
        )
    elif node.kind in ("CONV_2D", "DEPTHWISE_CONV_2D", "FULLY_CONNECTED"):
        source, weights, bias = (
            node.input(key) for key in ("input", "weights", "bias")
        )
        kind = {
            "CONV_2D": "Conv",
            "DEPTHWISE_CONV_2D": "Depthwise",
            "FULLY_CONNECTED": "FullyConnected",
        }[node.kind]
        lines.append(f"  tflite::{kind}Params params{{}};")
        fields(
            {
                "input_offset": f"-{parameter('input_zero_point')}",
                "output_offset": parameter("output_zero_point"),
                "quantized_activation_min": parameter("output_activation_min"),
                "quantized_activation_max": parameter("output_activation_max"),
            }
        )
        if node.kind == "FULLY_CONNECTED":
            fields(
                {
                    "weights_offset": f"-{parameter('filter_zero_point')}",
                    "output_multiplier": parameter("output_multiplier"),
                    "output_shift": parameter("output_shift"),
                }
            )
            prefix = "params, "
            call = "FullyConnected"
        else:
            fields(
                {
                    "stride_height": selection.geometry.stride[0],
                    "stride_width": selection.geometry.stride[1],
                    "dilation_height_factor": selection.geometry.dilation[0],
                    "dilation_width_factor": selection.geometry.dilation[1],
                    "padding_values.height": parameter("padding_height"),
                    "padding_values.width": parameter("padding_width"),
                }
            )
            if node.kind == "DEPTHWISE_CONV_2D":
                fields({"depth_multiplier": selection.geometry.depth_multiplier})
            prefix = f"params, {parameter('multipliers')}, {parameter('shifts')}, "
            call = (
                "ConvPerChannel"
                if node.kind == "CONV_2D"
                else "DepthwiseConvPerChannel"
            )
        bias_shape = shape(bias) if bias is not None else "tflite::RuntimeShape()"
        bias_data = (
            tensor(bias) if bias is not None else "static_cast<const int32_t*>(nullptr)"
        )
        lines.append(
            f"  tflite::reference_integer_ops::{call}({prefix}{shape(source)}, {tensor(source)}, {shape(weights)}, {tensor(weights)}, {bias_shape}, {bias_data}, {shape(output)}, {tensor(output)});"
        )
    elif node.kind == "ADD":
        lines.append("  tflite::ArithmeticParams params{};")
        fields(
            {
                key: parameter(key)
                for key in (
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
                )
            }
        )
        fields(
            {
                "quantized_activation_min": parameter("output_activation_min"),
                "quantized_activation_max": parameter("output_activation_max"),
            }
        )
        a, b = node.input("lhs"), node.input("rhs")
        lines.append(
            f"  tflite::reference_integer_ops::Add(params, {shape(a)}, {tensor(a)}, {shape(b)}, {tensor(b)}, {shape(output)}, {tensor(output)});"
        )
    elif node.kind == "AVERAGE_POOL_2D":
        lines.append("  tflite::PoolParams params{};")
        fields(
            {
                "stride_height": node.options.stride_h,
                "stride_width": node.options.stride_w,
                "filter_height": node.options.filter_h,
                "filter_width": node.options.filter_w,
                "padding_values.height": parameter("padding_height"),
                "padding_values.width": parameter("padding_width"),
                "quantized_activation_min": parameter("activation_min"),
                "quantized_activation_max": parameter("activation_max"),
            }
        )
        source = node.input("input")
        lines.append(
            f"  if (!tflite::reference_integer_ops::AveragePool(params, {shape(source)}, {tensor(source)}, {shape(output)}, {tensor(output)})) return 3;"
        )
    elif node.kind == "RESHAPE":
        source = node.input("input")
        if memory.tensors[source].offset != memory.tensors[output].offset:
            lines.append(
                f"  std::memcpy({tensor(output)}, {tensor(source)}, {graph.tensors[output].byte_length});"
            )
        else:
            lines.append("  // Proven read-only Reshape view; storage already aliases.")
    elif node.kind == "SOFTMAX":
        source = node.input("input")
        lines.extend(
            [
                "  int32_t sum; int exponent;",
                f"  return cc_softmax({tensor(source)}, {graph.tensors[source].shape[-1]}, {parameter('input_multiplier')}, {parameter('input_left_shift')}, {parameter('diff_min')}, {tensor(output)}, &sum, &exponent);",
                "}",
            ]
        )
        return "\n".join(lines) + "\n"
    return "\n".join([*lines, "  return 0;", "}"]) + "\n"


def _execution(model: LoweredModel):
    graph, memory = model.graph, model.memory
    guard_bytes = max(64, memory.arena_alignment)
    standalone = runtime_mode(model.kernels) == "standalone"
    source = (
        TEMPLATES / ("project_preamble.cc" if standalone else "a0_preamble.cc")
    ).read_text()
    if runtime_mode(model.kernels) != "reference":
        source = "#define ARCH_PROJECT_PROJECT_NUMERICS 1\n" + source
    if runtime_mode(model.kernels) in ("project-kernels", "standalone"):
        source += '#include "kernels/project/operators.h"\n'
    if any(pointwise_block_size(n) for n in model.kernels.nodes):
        source += '#include "kernels/rv64imc/pointwise.h"\n'
    if model.kernels.configuration in ("X1", "X2", "X3", "X4"):
        source += '#include "kernels/xqmac8/dot8.h"\n'
    if model.kernels.configuration in ("X3", "X4"):
        source += '#include "kernels/xpostinc/pointwise.h"\n'
    if any(depthwise_filter_size(n) for n in model.kernels.nodes):
        source += '#include "kernels/rv64imc/depthwise.h"\n'
    if any(DW_ZERO in n.choices for n in model.kernels.nodes):
        source += '#include "kernels/xdwmac8/scalar.h"\n'
    if model.kernels.configuration == "X4":
        source += '#include "kernels/xdwmac8/depthwise.h"\n'
    if uses_stem_unroll(model.kernels):
        source += """// Target-only code-generation choice; native builds verify the same arithmetic.
#if defined(__GNUC__) && !defined(__clang__) && defined(__riscv) && __riscv_xlen == 64
#define B1_STEM_UNROLL __attribute__((optimize("unroll-loops")))
#else
#define B1_STEM_UNROLL
#endif
"""
    source += f"""
namespace {{
struct alignas({memory.arena_alignment}) GuardedArena {{
  uint8_t before[{guard_bytes}];
  alignas({memory.arena_alignment}) int8_t data[{memory.arena_bytes}];
  uint8_t after[{guard_bytes}];
}};
GuardedArena arena;
static_assert(offsetof(GuardedArena, data) == {guard_bytes}, "guard immediately precedes workspace");
static_assert(offsetof(GuardedArena, after) == {guard_bytes + memory.arena_bytes}, "guard immediately follows workspace");
bool input_ready = false, output_ready = false;
int failed_node = -1;
#if A0_CAPTURE
A0Capture capture = nullptr;
#endif
}}  // namespace
"""
    if model.kernels.configuration in ("X2", "X3", "X4"):
        source += '#include "kernels/xrequant/requant.h"\n'
        if any(ADD64_CHOICE in n.choices for n in model.kernels.nodes):
            source += '#include "kernels/xrequant/add64.h"\n'
    for t in graph.tensors:
        source += f"static constexpr int32_t dims_{t.index}[] = {{{', '.join(str(v) for v in t.shape)}}};\n"
        if t.storage == "runtime":
            position = memory.tensors[t.index]
            source += f'static_assert({position.offset} + {t.byte_length} <= {memory.arena_bytes}, "tensor {t.index} bounds");\n'
            source += f'static_assert({position.offset} % {position.alignment} == 0, "tensor {t.index} alignment");\n'
    # Some metadata constants (e.g. the shape operand) are not needed at runtime.
    source = source.replace(
        "static constexpr int32_t dims_",
        "[[maybe_unused]] static constexpr int32_t dims_",
    )
    mapping = []
    for node in graph.nodes:
        start = source.count("\n") + 1
        source += _node_code(model, node)
        mapping.append(
            {
                "node": node.index,
                "kind": node.kind,
                "symbol": f"a0_node_{node.index:02d}",
                "source": "model.cc",
                "line": start,
                "end_line": source.count("\n"),
                "inputs": list(node.source_inputs),
                "outputs": list(node.outputs),
                "output_offset": memory.tensors[node.outputs[0]].offset,
            }
        )
    inp, out = graph.inputs[0], graph.outputs[0]
    source += f"""
extern "C" bool a0_guards_ok() {{
  for (unsigned i = 0; i < {guard_bytes}; ++i)
    if (arena.before[i] != 0xa5 || arena.after[i] != 0x5a) return false;
  return true;
}}
static void reset_input_state() {{
  std::memset(arena.before, 0xa5, sizeof(arena.before));
  std::memset(arena.after, 0x5a, sizeof(arena.after));
  input_ready = true; output_ready = false; failed_node = -1;
}}
extern "C" int a0_set_input(const uint8_t* data, std::size_t size) {{
  if (!data || size != {graph.tensors[inp].byte_length}) return 3;
  reset_input_state();
  std::memcpy(arena.data + {memory.tensors[inp].offset}, data, size);
  return 0;
}}
extern "C" void a0_fill_input(uint32_t seed) {{
  reset_input_state();
  for (std::size_t i = 0; i < {graph.tensors[inp].byte_length}; ++i) {{
    seed = seed * 1664525u + 1013904223u;
    reinterpret_cast<uint8_t*>(arena.data)[{memory.tensors[inp].offset} + i] = static_cast<uint8_t>(seed >> 24);
  }}
}}
extern "C" int a0_failed_node() {{ return failed_node; }}
extern "C" const uint8_t* a0_output() {{
  return output_ready ? reinterpret_cast<const uint8_t*>(arena.data + {memory.tensors[out].offset}) : nullptr;
}}
extern "C" std::size_t a0_input_bytes() {{ return {graph.tensors[inp].byte_length}; }}
extern "C" std::size_t a0_output_bytes() {{ return {graph.tensors[out].byte_length}; }}
extern "C" std::size_t a0_workspace_bytes() {{ return {memory.arena_bytes}; }}
#if A0_CAPTURE
extern "C" void a0_set_capture(A0Capture callback) {{ capture = callback; }}
extern "C" uint8_t* a0_debug_guard(int side) {{ return side ? arena.after : arena.before; }}
#endif
extern "C" A0_NOINLINE int a0_invoke() {{
  if (!input_ready) {{ output_ready = false; return 3; }}
  input_ready = false; output_ready = false;
#if A0_CAPTURE
  if (!a0_guards_ok()) return 3;
#endif
  int status;
"""
    for node in graph.nodes:
        t = graph.tensors[node.outputs[0]]
        position = memory.tensors[t.index]
        source += f"""  status = a0_node_{node.index:02d}();
  if (status) {{ failed_node = {node.index}; return status; }}
#if A0_CAPTURE
  if (!a0_guards_ok() || (capture && capture({node.index}, {t.index}, arena.data + {position.offset}, {t.byte_length}))) {{ failed_node = {node.index}; return 3; }}
#endif
"""
    source += "  output_ready = true;\n  return 0;\n}\n"
    return source, {
        "schema_version": 1,
        "configuration": model.kernels.configuration,
        **(
            {"runtime": runtime_mode(model.kernels)}
            if runtime_mode(model.kernels) != "reference"
            else {}
        ),
        "inference_symbol": "a0_invoke",
        "nodes": mapping,
    }


def emit_cpp(model: LoweredModel, output: Path) -> dict:
    # Revalidate caller-supplied immutable objects before producing any file.
    validate_lowered_model(model)
    constants_h, constants_cc = _constants(model)
    execution, mapping = _execution(model)
    artifacts = {
        "model.h": (TEMPLATES / "a0_model.h").read_text(),
        "constants.h": constants_h,
        "constants.cc": constants_cc,
        "model.cc": execution,
        "source_map.json": canonical(mapping),
        "execution_plan.json": make_execution_plan(model, mapping).to_json(),
        "graph_ir.json": model.graph.to_json(),
        "prepared_ir.json": model.prepared.to_json(),
        "kernel_plan.json": model.kernels.to_json(),
        "kernel_memory_contracts.json": model.contracts.to_json(),
        "memory_plan.json": model.memory.to_json(),
    }

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], check=True, text=True, capture_output=True
        ).stdout.strip()

    sources = [
        "compiler/depthwise.py",
        "compiler/requantization.py",
        "compiler/project_runtime.py",
        "compiler/lowering.py",
        "compiler/compilation.py",
        "compiler/emit_cpp.py",
        "compiler/execution_plan.py",
        "compiler/ir.py",
        "compiler/quantization.py",
        "compiler/kernel_plan.py",
        "compiler/memory_plan.py",
        "compiler/frontend.py",
        "compiler/validation.py",
        "compiler/cli.py",
        "kernels/reference/numerics.cc",
        "kernels/reference/numerics.h",
    ]
    sources += [str(p.relative_to(ROOT)) for p in sorted(TEMPLATES.glob("a0_*"))]
    pointwise = any(pointwise_block_size(n) for n in model.kernels.nodes)
    depthwise = any(depthwise_filter_size(n) for n in model.kernels.nodes)
    optimized = pointwise or depthwise
    if optimized:
        sources.append("kernels/rv64imc/quantization_select.h")
    if runtime_mode(model.kernels) in ("project-kernels", "standalone"):
        sources.append("kernels/project/operators.h")
    if runtime_mode(model.kernels) == "standalone":
        sources += [
            "kernels/project/softmax.h",
            "kernels/project/softmax.cc",
            "kernels/project/replay.cc",
            "kernels/project/numerics.h",
        ]
    if runtime_mode(model.kernels) != "reference":
        sources += [
            "kernels/project/quantization.h",
            "kernels/project/quantization.cc",
            "kernels/project/NOTICE",
            "kernels/project/LICENSE",
        ]
    if pointwise:
        sources.append("kernels/rv64imc/pointwise.h")
    if model.kernels.configuration in ("X1", "X2", "X3", "X4"):
        sources.append("kernels/xqmac8/dot8.h")
    if depthwise:
        sources.append("kernels/rv64imc/depthwise.h")
    if runtime_mode(model.kernels) == "standalone":
        sources = [n for n in sources if not n.startswith("kernels/reference/")]
        sources.append("compiler/templates/project_preamble.cc")
    if model.kernels.configuration in ("X2", "X3", "X4"):
        sources += [
            "compiler/xrequant.py",
            "tools/xrequant/contract.py",
            "kernels/xrequant/requant.h",
        ]
        if any(ADD64_CHOICE in n.choices for n in model.kernels.nodes):
            sources.append("kernels/xrequant/add64.h")
    if model.kernels.configuration in ("X3", "X4"):
        sources += [
            "compiler/xpostinc.py",
            "tools/xpostinc/contract.py",
            "kernels/xpostinc/memory.h",
            "kernels/xpostinc/pointwise.h",
        ]
    if any(DW_ZERO in n.choices for n in model.kernels.nodes):
        sources.append("kernels/xdwmac8/scalar.h")
    if model.kernels.configuration == "X4":
        sources += [
            "kernels/xdwmac8/bank.h",
            "kernels/xdwmac8/depthwise.h",
            "tools/xdwmac8/contract.py",
        ]
    manifest = {
        "schema_version": 1,
        "stage": 11
        if model.kernels.configuration == "X4"
        else 10
        if model.kernels.configuration in ("X3", "X4")
        else 8
        if model.kernels.configuration in ("X2", "X3", "X4")
        else 7
        if model.kernels.configuration in ("X1", "X2", "X3", "X4")
        else 6
        if depthwise
        else 5
        if model.kernels.configuration == "B1"
        else 4,
        "configuration": model.kernels.configuration,
        **(
            {
                "isa_extensions": (
                    ["xqmac8", "xrequant", "xpostinc", "xdwmac8"]
                    if model.kernels.configuration == "X4"
                    else ["xqmac8", "xrequant", "xpostinc"]
                    if model.kernels.configuration in ("X3", "X4")
                    else ["xqmac8", "xrequant"]
                    if model.kernels.configuration in ("X2", "X3", "X4")
                    else ["xqmac8"]
                ),
                "xqmac8_contract_version": 1,
            }
            if model.kernels.configuration in ("X1", "X2", "X3", "X4")
            else {}
        ),
        **(
            {"runtime": runtime_mode(model.kernels)}
            if runtime_mode(model.kernels) != "reference"
            else {}
        ),
        "repository_revision": git("rev-parse", "HEAD"),
        "repository_dirty_status": git("status", "--porcelain"),
        "reference_revision": model.graph.reference_revision,
        "model_sha256": model.graph.model_sha256,
        "graph_ir_sha256": model.context.graph_sha256,
        "prepared_ir_sha256": model.prepared.sha256,
        "memory_plan_sha256": model.memory.sha256,
        "kernel_plan_sha256": model.kernels.sha256,
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sources
        },
        "artifacts": {
            name: hashlib.sha256(text.encode()).hexdigest()
            for name, text in artifacts.items()
        },
        "capabilities": {
            "inference_codegen": True,
            "reference_execution": not optimized,
            "optimized_kernels": optimized,
            **(
                {"standalone_target": True}
                if runtime_mode(model.kernels) == "standalone"
                else {}
            ),
        },
        "passes": [
            "stage1_validation",
            "stage2_integer_preparation",
            "stage3_memory_proof",
            (
                "validated_b1_depthwise_selection"
                if depthwise
                else (
                    "validated_b1_pointwise_selection"
                    if pointwise
                    else "validated_reference_kernel_selection"
                )
            ),
            "explicit_static_shapes_and_scalars",
            "static_cpp_emission",
            *(
                ["validated_runtime_" + runtime_mode(model.kernels)]
                if runtime_mode(model.kernels) != "reference"
                else []
            ),
        ],
        "measurement": {
            "entry": "a0_invoke",
            "stable_nodes": True,
            "capture": "diagnostic build only",
            "softmax_preflight": "extra exp/sum pass retains pinned input-domain validation",
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, content in artifacts.items():
        (output / name).write_text(content)
    (output / "manifest.json").write_text(canonical(manifest))
    return manifest
