"""Explicit project runtime selections; no checkpoint label selects code."""

from dataclasses import replace
from .ir import ModelError

RUNTIMES = ("reference", "project-numerics", "project-kernels", "standalone")


def runtime_mode(plan):
    for mode in RUNTIMES[1:]:
        if any(f"runtime_{mode}" in n.choices for n in plan.nodes):
            return mode
    return "reference"


def saved_runtime(nodes):
    return next(
        (
            mode
            for mode in RUNTIMES[1:]
            if any(f"runtime_{mode}" in n["choices"] for n in nodes)
        ),
        "reference",
    )


def apply_runtime(graph, nodes, mode):
    if mode == "reference":
        return tuple(nodes)
    result = []
    for n in nodes:
        impl = n.implementation
        own = impl.startswith("rv64imc/")
        if mode in ("project-kernels", "standalone"):
            g = n.geometry
            if n.kind == "CONV_2D" and not own:
                if not (
                    g.weight_shape[1:] == (3, 3, 3)
                    and g.stride == (2, 2)
                    and g.dilation == (1, 1)
                    and g.input_shape[0] == g.output_shape[0] == 1
                ):
                    raise ModelError(f"node {n.node}: unsupported project convolution")
                impl = "project/stem_rgb3x3/int8"
            elif n.kind == "DEPTHWISE_CONV_2D" and not own:
                raise ModelError(
                    f"node {n.node}: project runtime requires eligible depthwise selection"
                )
            elif n.kind == "ADD":
                node = graph.nodes[n.node]
                if any(
                    graph.tensors[i].shape != g.output_shape
                    for i in node.source_inputs
                    if i >= 0
                ):
                    raise ModelError(
                        f"node {n.node}: project ADD requires equal shapes"
                    )
                p = dict(n.scalar_parameters)
                if (
                    any(
                        not -31 <= p[k] <= 0
                        for k in ("input1_shift", "input2_shift", "output_shift")
                    )
                    or not 0 <= p["left_shift"] <= 30
                ):
                    raise ModelError(f"node {n.node}: unsupported project ADD shifts")
                impl = "project/add/int8"
            elif n.kind == "AVERAGE_POOL_2D":
                node = graph.nodes[n.node]
                if not (
                    g.output_shape[1:3] == (1, 1)
                    and node.options.filter_h == g.input_shape[1]
                    and node.options.filter_w == g.input_shape[2]
                    and not any(g.padding)
                    and g.input_shape[0] == g.output_shape[0]
                    and g.input_shape[3] == g.output_shape[3]
                    and g.input_shape[1] * g.input_shape[2] <= (2**31 - 1) // 129
                ):
                    raise ModelError(
                        f"node {n.node}: project pooling requires unpadded global average"
                    )
                impl = "project/global_average/int8"
            elif n.kind == "FULLY_CONNECTED":
                if dict(n.scalar_parameters)["filter_zero_point"] != 0:
                    raise ModelError(
                        f"node {n.node}: project FC requires symmetric weights"
                    )
                impl = "project/fully_connected/int8"
            elif n.kind == "QUANTIZE":
                impl = "project/boundary/8bit"
            elif n.kind == "RESHAPE":
                impl = "project/reshape_view/int8"
            elif n.kind == "SOFTMAX" and mode == "standalone":
                impl = "project/softmax/int8"
            own = impl.startswith(("rv64imc/", "project/"))
        result.append(
            replace(
                n,
                implementation=impl,
                arithmetic_backend="project_scalar_integer_rv64imc"
                if own
                else n.arithmetic_backend,
                requantization_backend="none"
                if impl in ("project/reshape_view/int8", "project/global_average/int8")
                else "project_double_rounding"
                if own
                else n.requantization_backend,
                reduction_backend=(
                    {
                        "CONV_2D": "scalar_fixed_rgb",
                        "FULLY_CONNECTED": "scalar_dot8_offset",
                        "ADD": "scalar_elementwise",
                        "AVERAGE_POOL_2D": "scalar_spatial_sum",
                        "QUANTIZE": "scalar_boundary",
                        "RESHAPE": "none",
                        "SOFTMAX": "scalar_fixedpoint_softmax",
                    }.get(n.kind, n.reduction_backend)
                    if impl.startswith("project/")
                    else n.reduction_backend
                ),
                choices=(*n.choices, f"runtime_{mode}"),
                memory=replace(
                    n.memory,
                    implementation=impl,
                    stack_policy="fixed scalar locals and pointers; no arena scratch"
                    if impl.startswith("project/")
                    else n.memory.stack_policy,
                ),
            )
        )
    return tuple(result)
