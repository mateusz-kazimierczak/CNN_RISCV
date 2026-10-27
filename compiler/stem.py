"""X5: shared RGB patches, offline padded weights, and exact valid-tap biases."""

from dataclasses import replace
import struct

from .depthwise import valid_regions
from .ir import ModelError

STEM = "stem_rgb_patch27_xqmac8_padded32_v1"
IMPLEMENTATION = "rv64imc/stem_rgb_xqmac8/int8"


def stem_tables(graph, selection, prepared):
    g = selection.geometry
    if (
        g.weight_shape[1:] != (3, 3, 3)
        or g.stride != (2, 2)
        or g.dilation != (1, 1)
        or g.input_shape[0] != 1
    ):
        raise ModelError("packed RGB stem requires batch-one 3x3x3 stride-two geometry")
    oc = g.output_shape[-1]
    node = graph.nodes[selection.node]
    weights = graph.constant_values(node.input("weights"))
    bias = node.input("bias")
    original_bias = graph.constant_values(bias) if bias is not None else [0] * oc
    regions, ids = valid_regions(g)
    corrected = []
    for y0, y1, x0, x1 in regions:
        for ch in range(oc):
            ws = [
                weights[ch * 27 + (fy * 3 + fx) * 3 + c]
                for fy in range(y0, y1)
                for fx in range(x0, x1)
                for c in range(3)
            ]
            b = original_bias[ch] + prepared.input_offsets[0] * sum(ws)
            lo = b + sum(min(-128 * v, 127 * v) for v in ws)
            hi = b + sum(max(-128 * v, 127 * v) for v in ws)
            if not -(1 << 31) <= lo <= b <= hi < (1 << 31):
                raise ModelError("packed RGB stem INT32 prefix bound failed")
            corrected.append(b)
    packed = b"".join(
        bytes(v & 255 for v in weights[ch * 27 : (ch + 1) * 27]) + bytes(5)
        for ch in range(oc)
    )
    return (
        tuple(corrected),
        tuple(ids),
        struct.unpack("<" + "i" * (len(packed) // 4), packed),
    )


def select_stem(parent, graph, prepared):
    nodes = []
    selected = 0
    for n, p in zip(parent.nodes, prepared.nodes):
        if n.implementation != "project/stem_rgb3x3/int8":
            nodes.append(n)
            continue
        biases, regions, weights = stem_tables(graph, n, p)
        nodes.append(
            replace(
                n,
                implementation=IMPLEMENTATION,
                arithmetic_backend="xqmac8_stem27_padded32+xrequant_v1",
                reduction_backend="xqmac8_stem27_padded32",
                weight_layout="OHWI padded to 32 bytes per output channel",
                corrected_bias_eligible=True,
                choices=(*n.choices, STEM),
                memory=replace(
                    n.memory,
                    implementation=IMPLEMENTATION,
                    stem_biases=biases,
                    stem_regions=regions,
                    stem_weights=weights,
                ),
            )
        )
        selected += 1
    if selected != 1:
        raise ModelError("X5 requires exactly one supported RGB stem")
    return replace(parent, nodes=tuple(nodes), configuration="X5")
