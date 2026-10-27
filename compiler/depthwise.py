"""Exact region-specific depthwise bias correction and X4 bank scheduling."""

from dataclasses import replace
from .ir import ModelError

ZERO = "depthwise_zero_point_hoisted_v1"
BANK = "xdwmac8_accumulator_bank_v1"


def zero_policy(nodes):
    return (
        "regions"
        if any(
            ZERO in (n["choices"] if isinstance(n, dict) else n.choices) for n in nodes
        )
        else "none"
    )


def valid_regions(g):
    _, h, w, _ = g.input_shape
    _, oh, ow, _ = g.output_shape
    f = g.weight_shape[1]
    sh, sw = g.stride
    top, _, left, _ = g.padding
    regions = []
    ids = []
    for y in range(oh):
        for x in range(ow):
            oy, ox = y * sh - top, x * sw - left
            region = (max(0, -oy), min(f, h - oy), max(0, -ox), min(f, w - ox))
            if region not in regions:
                regions.append(region)
            ids.append(regions.index(region))
    return regions, ids


def correction_tables(graph, selection, prepared):
    g = selection.geometry
    c = g.input_shape[-1]
    f = g.weight_shape[1]
    regions, ids = valid_regions(g)
    node = graph.nodes[selection.node]
    weights = graph.constant_values(node.input("weights"))
    bias_id = node.input("bias")
    biases = graph.constant_values(bias_id) if bias_id is not None else [0] * c
    offset = prepared.input_offsets[0]
    corrected = []
    for y0, y1, x0, x1 in regions:
        for ch in range(c):
            ws = [
                weights[(fy * f + fx) * c + ch]
                for fy in range(y0, y1)
                for fx in range(x0, x1)
            ]
            b = biases[ch] + offset * sum(ws)
            lo = b + sum(min(-128 * v, 127 * v) for v in ws)
            hi = b + sum(max(-128 * v, 127 * v) for v in ws)
            # These monotone bounds contain every bias-first accumulator prefix.
            if not -(1 << 31) <= lo <= b <= hi < (1 << 31):
                raise ModelError(
                    f"node {selection.node}: corrected depthwise INT32 prefix bound failed"
                )
            corrected.append(b)
    return tuple(corrected), tuple(ids)


def select_depthwise(parent, graph, prepared, *, zero="none", bank=False):
    if zero not in ("none", "regions"):
        raise ModelError("invalid depthwise zero-point policy")
    if bank and zero != "regions":
        raise ModelError("X4 requires region-specific zero-point correction")
    from .kernel_plan import depthwise_filter_size
    from .xpostinc import DEPTHWISE

    nodes = []
    for n, p in zip(parent.nodes, prepared.nodes):
        if not depthwise_filter_size(n) or zero == "none":
            nodes.append(n)
            continue
        biases, regions = correction_tables(graph, n, p)
        choices = (*n.choices, ZERO)
        if bank:
            choices = tuple(v for v in choices if v != DEPTHWISE) + (BANK,)
        nodes.append(
            replace(
                n,
                choices=choices,
                reduction_backend="xdwmac8_bank" if bank else n.reduction_backend,
                memory=replace(
                    n.memory, depthwise_biases=biases, depthwise_regions=regions
                ),
            )
        )
    return replace(
        parent, nodes=tuple(nodes), configuration="X4" if bank else parent.configuration
    )


def bank_counts(selection, work):
    if BANK not in selection.choices:
        return {}
    g = selection.geometry
    b, oh, ow, c = g.output_shape
    blocks = b * oh * ow * (c // 8)
    taps = work["executed_products"] // c
    return {
        "xdwmac8": taps * (c // 8),
        **{f"xdwset{i}": blocks for i in range(4)},
        **{f"xdwget{i}": blocks for i in range(4)},
    }
