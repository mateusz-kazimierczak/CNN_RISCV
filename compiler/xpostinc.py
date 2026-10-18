"""Explicit X3 memory policy and compiler-derived dynamic operation counts."""

from dataclasses import replace

from .ir import ModelError

POINTWISE = "xpostinc_pointwise_groups_v1"
DEPTHWISE = "xpostinc_depthwise_border_and_output_v1"


SELECTED = "xpostinc_depthwise_policy_selected_v1"
NONE = "xpostinc_depthwise_policy_none_v1"


def depthwise_policy(nodes):
    choices = {
        c for n in nodes for c in (n["choices"] if isinstance(n, dict) else n.choices)
    }
    return "selected" if SELECTED in choices else "none" if NONE in choices else "all"


def selected_depthwise(n):
    # Measured on pinned GCC: 3x3 stride-one and the 96-channel stride-two stem block.
    return n.geometry.weight_shape[1:3] == (3, 3) and (
        n.geometry.stride == (1, 1) or n.geometry.input_shape[-1] == 96
    )


def select_x3(parent, depthwise="all"):
    if depthwise not in ("all", "selected", "none"):
        raise ModelError("invalid Xpostinc depthwise policy")
    from .kernel_plan import depthwise_filter_size, pointwise_block_size

    nodes = []
    for n in parent.nodes:
        marker = None
        if n.reduction_backend.startswith("xqmac8"):
            if pointwise_block_size(n) not in (2, 4):
                raise ModelError("X3 requires blocked pointwise reductions")
            marker = POINTWISE
        elif depthwise_filter_size(n):
            if depthwise != "all":
                n = replace(
                    n,
                    choices=(*n.choices, SELECTED if depthwise == "selected" else NONE),
                )
            if depthwise == "all" or (
                depthwise == "selected" and selected_depthwise(n)
            ):
                if n.geometry.input_shape[-1] > 2047:
                    raise ModelError("X3 depthwise channel stride exceeds imm12")
                marker = DEPTHWISE
        nodes.append(replace(n, choices=(*n.choices, marker)) if marker else n)
    return replace(parent, configuration="X3", nodes=tuple(nodes))


def expected_counts(selection, work):
    """Counts follow loop schedules, including border clipping and odd tails."""
    from .kernel_plan import (
        depthwise_filter_size,
        pointwise_block_size,
        pointwise_pixels,
    )

    g = selection.geometry
    loads = stores = 0
    if POINTWISE in selection.choices:
        pixels = g.output_shape[0] * g.output_shape[1] * g.output_shape[2]
        channels = g.output_shape[-1]
        block = pointwise_block_size(selection)
        tile = pointwise_pixels(selection)
        groups = (
            (pixels // tile + pixels % tile)
            * (channels // block)
            * (g.input_shape[-1] // 8)
        )
        loads = groups * 2
        stores = (pixels if tile == 1 else pixels % 2) * channels
    elif DEPTHWISE in selection.choices:
        b, h, w, c = g.input_shape
        _, oh, ow, _ = g.output_shape
        f = depthwise_filter_size(selection)
        sh, sw = g.stride
        top, _, left, _ = g.padding
        inside_h = sum(0 <= y * sh - top and y * sh - top + f <= h for y in range(oh))
        inside_w = sum(0 <= x * sw - left and x * sw - left + f <= w for x in range(ow))
        inside_products = b * inside_h * inside_w * c * f * f
        loads = 2 * (work["executed_products"] - inside_products)
        stores = b * oh * ow * c
    return {"load": loads, "store": stores}
