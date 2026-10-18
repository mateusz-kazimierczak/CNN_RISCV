"""Choose project-owned runtime pieces after the kernel schedule is selected.

The mode changes implementations and their evidence contracts. It never changes
prepared parameters, operand layouts or physical memory placement. The reference
mode leaves the earlier selections intact; standalone forbids hidden fallbacks.
"""

from dataclasses import replace

from .ir import ModelError

RUNTIMES = ("reference", "project-numerics", "project-kernels", "standalone")
PROJECT_REDUCTIONS = {
    "CONV_2D": "scalar_fixed_rgb",
    "FULLY_CONNECTED": "scalar_dot8_offset",
    "ADD": "scalar_elementwise",
    "AVERAGE_POOL_2D": "scalar_spatial_sum",
    "QUANTIZE": "scalar_boundary",
    "RESHAPE": "none",
    "SOFTMAX": "scalar_fixedpoint_softmax",
}
UNSCALED_IMPLEMENTATIONS = {"project/reshape_view/int8", "project/global_average/int8"}


def runtime_mode(plan):
    """Recover the explicit mode from a validated typed plan."""
    for mode in RUNTIMES[1:]:
        if any(f"runtime_{mode}" in node.choices for node in plan.nodes):
            return mode
    return "reference"


def saved_runtime(nodes):
    """Read the mode hint; the caller subsequently validates the entire plan.

    This is not permission to trust a saved choice. Reconstructing the canonical
    plan rejects unknown markers, mixed modes and forged implementation facts.
    """
    return next(
        (
            mode
            for mode in RUNTIMES[1:]
            if any(f"runtime_{mode}" in node["choices"] for node in nodes)
        ),
        "reference",
    )


def _project_implementation(graph, selection, mode):
    """Replace only the supported static operator subsets; reject other shapes."""
    implementation = selection.implementation
    if implementation.startswith("rv64imc/"):
        # The preceding selector already proved the pointwise/depthwise schedule.
        return implementation

    geometry = selection.geometry
    node = graph.nodes[selection.node]
    parameters = dict(selection.scalar_parameters)
    if selection.kind == "CONV_2D":
        is_rgb_stem = (
            geometry.weight_shape[1:] == (3, 3, 3)
            and geometry.stride == (2, 2)
            and geometry.dilation == (1, 1)
            and geometry.input_shape[0] == geometry.output_shape[0] == 1
        )
        if not is_rgb_stem:
            raise ModelError(f"node {node.index}: unsupported project convolution")
        return "project/stem_rgb3x3/int8"
    if selection.kind == "DEPTHWISE_CONV_2D":
        raise ModelError(
            f"node {node.index}: project runtime requires eligible depthwise selection"
        )
    if selection.kind == "ADD":
        equal_shapes = all(
            graph.tensors[index].shape == geometry.output_shape
            for index in node.source_inputs
            if index >= 0
        )
        if not equal_shapes:
            raise ModelError(f"node {node.index}: project ADD requires equal shapes")
        supported_shifts = (
            all(
                -31 <= parameters[key] <= 0
                for key in ("input1_shift", "input2_shift", "output_shift")
            )
            and 0 <= parameters["left_shift"] <= 30
        )
        if not supported_shifts:
            raise ModelError(f"node {node.index}: unsupported project ADD shifts")
        return "project/add/int8"
    if selection.kind == "AVERAGE_POOL_2D":
        is_global_pool = (
            geometry.output_shape[1:3] == (1, 1)
            and node.options.filter_h == geometry.input_shape[1]
            and node.options.filter_w == geometry.input_shape[2]
            and not any(geometry.padding)
            and geometry.input_shape[0] == geometry.output_shape[0]
            and geometry.input_shape[3] == geometry.output_shape[3]
            # Leave room for signed rounding as well as the sum itself.
            and geometry.input_shape[1] * geometry.input_shape[2] <= (2**31 - 1) // 129
        )
        if not is_global_pool:
            raise ModelError(
                f"node {node.index}: project pooling requires unpadded global average"
            )
        return "project/global_average/int8"
    if selection.kind == "FULLY_CONNECTED":
        if parameters["filter_zero_point"] != 0:
            raise ModelError(
                f"node {node.index}: project FC requires symmetric weights"
            )
        return "project/fully_connected/int8"
    if selection.kind == "QUANTIZE":
        return "project/boundary/8bit"
    if selection.kind == "RESHAPE":
        return "project/reshape_view/int8"
    if selection.kind == "SOFTMAX" and mode == "standalone":
        return "project/softmax/int8"
    return implementation


def apply_runtime(graph, nodes, mode):
    """Attach the selected implementations and matching numerical evidence."""
    if mode == "reference":
        return tuple(nodes)
    result = []
    for selection in nodes:
        implementation = selection.implementation
        if mode in ("project-kernels", "standalone"):
            implementation = _project_implementation(graph, selection, mode)

        uses_project_arithmetic = implementation.startswith(("rv64imc/", "project/"))
        is_project_operator = implementation.startswith("project/")
        if implementation in UNSCALED_IMPLEMENTATIONS:
            requantization = "none"
        elif uses_project_arithmetic:
            requantization = "project_double_rounding"
        else:
            requantization = selection.requantization_backend
        reduction = selection.reduction_backend
        if is_project_operator:
            reduction = PROJECT_REDUCTIONS.get(selection.kind, reduction)

        result.append(
            replace(
                selection,
                implementation=implementation,
                arithmetic_backend="project_scalar_integer_rv64imc"
                if uses_project_arithmetic
                else selection.arithmetic_backend,
                requantization_backend=requantization,
                reduction_backend=reduction,
                choices=(*selection.choices, f"runtime_{mode}"),
                memory=replace(
                    selection.memory,
                    implementation=implementation,
                    stack_policy="fixed scalar locals and pointers; no arena scratch"
                    if is_project_operator
                    else selection.memory.stack_policy,
                ),
            )
        )
    return tuple(result)
