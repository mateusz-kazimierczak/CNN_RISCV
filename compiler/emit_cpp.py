"""Deterministic C++17 A0 emission from validated arithmetic and memory plans."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .execution_plan import make_execution_plan
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
    for p, node in zip(memory.parameters, model.prepared.nodes):
        if not p.size_bytes:
            continue
        values = []
        for key, _, _ in p.fields:
            v = node.integers[key]
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


def _node_code(model: LoweredModel, node):
    graph, prepared, memory = (
        model.graph,
        model.prepared.nodes[node.index],
        model.memory,
    )
    p = prepared.integers
    selection = model.kernels.nodes[node.index]
    scalars = dict(selection.scalar_parameters)
    lines = [
        f'extern "C" A0_NOINLINE int a0_node_{node.index:02d}() {{',
        "  A0_NODE_ENTRY();",
    ]

    def tensor(index):
        t = graph.tensors[index]
        if t.storage == "constant":
            return f"a0_constants.t{index}"
        offset = memory.tensors[index].offset
        return f"(arena.data + {offset})"

    def shape(index):
        return f"a0_static_shape<{len(graph.tensors[index].shape)}>(dims_{index})"

    def parameter(key):
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
    source = (TEMPLATES / "a0_preamble.cc").read_text()
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
        "configuration": "A0",
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
    manifest = {
        "schema_version": 1,
        "stage": 4,
        "configuration": "A0",
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
            "reference_execution": True,
            "optimized_kernels": False,
        },
        "passes": [
            "stage1_validation",
            "stage2_integer_preparation",
            "stage3_memory_proof",
            "validated_reference_kernel_selection",
            "explicit_static_shapes_and_scalars",
            "static_cpp_emission",
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
