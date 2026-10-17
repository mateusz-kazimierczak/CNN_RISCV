"""Stage 2: independent offline preparation and checked integer contracts.

Preparation follows the pinned *_common.cc and kernels/kernel_util.cc. In
particular FC multiplies its two scales in binary32; Conv does so in binary64.
No floating point is used by the scalar execution helpers below.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import asdict, dataclass

from .ir import Graph, ModelError, Node
from .validation import validate_graph

I32_MIN = -(1 << 31)
I32_MAX = (1 << 31) - 1
ARITHMETIC = {
    "reference": "TFLM 9f638f18154dff868e7053572f089be845b2fbdf",
    "single_rounding": False,
    "emulate_float": False,
    "preparation": "offline; IEEE binary32 metadata and binary64 frexp",
    "high_multiply": "saturating doubling high multiply; nearest, ties toward +infinity",
    "divide_by_power_of_two": "nearest, ties away from zero",
    "right_shift": "arithmetic (floor); required and compile-checked for reused C++17 helpers",
    "accumulators": "INT32; wide offline bounds include every prefix; reject overflow",
    "left_shift": "multiply by power of two after checked INT32 range",
    "activation": "requantize, add output zero point, clamp to fused bounds, narrow",
    "pool": "sum valid taps; nearest ties away from zero; exclude padding from divisor",
    "quantize_boundaries": "same-scale signed/unsigned 128 shift; preserve both graph nodes",
    "softmax": "reuse pinned Q5.26 exp / Q12 accumulation / reciprocal; exponent 0..31 required",
    "runtime_parameters": [
        "accumulators",
        "pool valid-tap sum/count",
        "softmax row max/sum/reciprocal/exponent",
    ],
}


def i32(value: int) -> int:
    if not I32_MIN <= value <= I32_MAX:
        raise ModelError(f"integer outside INT32 contract: {value}")
    return value


def f32(value: float) -> float:
    try:
        return struct.unpack("<f", struct.pack("<f", value))[0]
    except OverflowError as error:
        raise ModelError("offline preparation exceeded binary32 range") from error


def round_away(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def quantize_multiplier(value: float) -> tuple[int, int]:
    if not math.isfinite(value) or value < 0:
        raise ModelError("multiplier must be finite and nonnegative")
    if value == 0:
        return 0, 0
    fraction, shift = math.frexp(value)
    multiplier = round_away(fraction * (1 << 31))
    if multiplier == 1 << 31:
        multiplier //= 2
        shift += 1
    if shift < -31:
        return 0, 0
    if shift > 30:
        raise ModelError("multiplier shift exceeds checked double-rounding runtime")
    return i32(multiplier), shift


def trunc_div(value: int, divisor: int) -> int:
    return (1 if value >= 0 else -1) * (abs(value) // divisor)


def high_mul(a: int, b: int) -> int:
    i32(a)
    i32(b)
    if a == b == I32_MIN:
        return I32_MAX
    product = a * b
    return i32(
        trunc_div(product + ((1 << 30) if product >= 0 else 1 - (1 << 30)), 1 << 31)
    )


def rounding_divide(value: int, exponent: int) -> int:
    i32(value)
    if not 0 <= exponent <= 31:
        raise ModelError("rounding shift outside 0..31")
    quotient = value // (1 << exponent)
    remainder = value - quotient * (1 << exponent)
    threshold = (((1 << exponent) - 1) // 2) + (value < 0)
    return quotient + (remainder > threshold)


def requantize(value: int, multiplier: int, shift: int) -> int:
    if not -31 <= shift <= 30 or not 0 <= multiplier <= I32_MAX:
        raise ModelError("requantization parameters outside checked contract")
    shifted = i32(i32(value) * (1 << max(shift, 0)))
    return rounding_divide(high_mul(shifted, multiplier), max(-shift, 0))


def clamp(value: int, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, value))


def activation_range(tensor, activation: str) -> tuple[int, int]:
    q = tensor.quantization
    minimum, maximum = (-128, 127) if tensor.dtype == "INT8" else (0, 255)

    def quant(value):
        return i32(round_away(f32(value / q.scales[0])) + q.zero_points[0])

    if activation == "RELU":
        minimum = max(minimum, quant(0))
    elif activation == "RELU6":
        minimum, maximum = max(minimum, quant(0)), min(maximum, quant(6))
    elif activation == "RELU_N1_TO_1":
        minimum, maximum = max(minimum, quant(-1)), min(maximum, quant(1))
    elif activation != "NONE":
        raise ModelError(f"unsupported integer activation: {activation}")
    if minimum > maximum:
        raise ModelError("empty fused activation range")
    return minimum, maximum


def dot(inputs, weights, input_offset: int, bias: int | None = None) -> int:
    if len(inputs) != len(weights):
        raise ModelError("dot-product length mismatch")
    accumulator = 0
    for x, w in zip(inputs, weights):
        if not -128 <= x <= 127 or not -128 <= w <= 127:
            raise ModelError("dot-product operands must be INT8")
        accumulator = i32(accumulator + (x + input_offset) * w)
    return i32(accumulator + (bias or 0))


def adjusted_bias(weights, input_offset: int, bias: int | None = None) -> int:
    # Python integers are wide: narrowing is explicit, never modulo 2**32.
    return i32((bias or 0) + input_offset * sum(weights))


def add_scalar(x: int, y: int, params: dict) -> int:
    p = params
    if not -128 <= x <= 127 or not -128 <= y <= 127:
        raise ModelError("ADD operands must be INT8")
    a = i32((x + p["input1_offset"]) * (1 << p["left_shift"]))
    b = i32((y + p["input2_offset"]) * (1 << p["left_shift"]))
    a = requantize(a, p["input1_multiplier"], p["input1_shift"])
    b = requantize(b, p["input2_multiplier"], p["input2_shift"])
    result = i32(
        requantize(i32(a + b), p["output_multiplier"], p["output_shift"])
        + p["output_offset"]
    )
    return clamp(result, p["output_activation_min"], p["output_activation_max"])


def average_pool(values, minimum=-128, maximum=127) -> int:
    if not -128 <= minimum <= maximum <= 127:
        raise ModelError("invalid INT8 pool activation range")
    if not values or any(not -128 <= x <= 127 for x in values):
        raise ModelError("pool requires at least one valid INT8 tap")
    count, total = len(values), i32(sum(values))
    rounded = trunc_div(
        i32(total + (count // 2 if total > 0 else -(count // 2))), count
    )
    return clamp(rounded, minimum, maximum)


@dataclass(frozen=True)
class PreparedNode:
    node: int
    kind: str
    integers: dict
    input_offsets: tuple[int, ...]
    output_offset: int
    effective_bias_scales: tuple[float, ...] = ()
    accumulator_abs_bounds: tuple[int, ...] = ()
    adjusted_biases: tuple[int, ...] | None = None
    padding_policy: str = "not applicable"


@dataclass(frozen=True)
class PreparedGraph:
    graph_ir_sha256: str
    model_sha256: str
    nodes: tuple[PreparedNode, ...]
    schema_version: int = 1

    def to_json(self) -> str:
        return (
            json.dumps(
                {
                    **asdict(self),
                    "arithmetic": ARITHMETIC,
                    "capabilities": {
                        "prepared_parameters": True,
                        "memory_plan": False,
                        "inference_codegen": False,
                    },
                },
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    @classmethod
    def from_json(cls, text: str, graph: Graph) -> PreparedGraph:
        """Revalidate all derived data against the source graph on reload."""
        expected = prepare_graph(graph)
        try:
            normalized = (
                json.dumps(json.loads(text), sort_keys=True, indent=2, allow_nan=False)
                + "\n"
            )
        except (TypeError, ValueError) as error:
            raise ModelError(f"invalid prepared IR: {error}") from error
        if normalized != expected.to_json():
            raise ModelError(
                "prepared IR differs from validated graph/arithmetic contract"
            )
        return expected


def _padding(node: Node) -> dict:
    p = node.padding
    return {
        "padding_height": p.top,
        "padding_width": p.left,
        "padding_height_offset": p.bottom - p.top,
        "padding_width_offset": p.right - p.left,
    }


def prepare_graph(graph: Graph) -> PreparedGraph:
    validate_graph(graph)
    prepared = []
    for node in graph.nodes:
        inputs = [graph.tensors[o.tensor] for o in node.inputs if o.tensor is not None]
        source, output = inputs[0], graph.tensors[node.outputs[0]]
        scale, zero = source.quantization.scales[0], source.quantization.zero_points[0]
        out_scale, out_zero = (
            output.quantization.scales[0],
            output.quantization.zero_points[0],
        )
        offsets = tuple(
            -t.quantization.zero_points[0] for t in inputs if t.dtype != "INT32"
        )
        p, bias_scales, bounds, corrections = {}, (), (), None
        policy = "not applicable"
        kind = node.kind
        if kind in ("CONV_2D", "DEPTHWISE_CONV_2D", "FULLY_CONNECTED"):
            weights = inputs[1]
            channels = (
                weights.shape[-1] if kind == "DEPTHWISE_CONV_2D" else weights.shape[0]
            )
            ws = weights.quantization.scales
            bias_scales = tuple(
                scale * ws[c if len(ws) > 1 else 0] for c in range(channels)
            )
            real_scales = tuple(v / out_scale for v in bias_scales)
            if kind == "FULLY_CONNECTED":
                bias_scales = (f32(scale * ws[0]),) * channels
                real_scales = (bias_scales[0] / out_scale,)
            multipliers, shifts = zip(*(quantize_multiplier(v) for v in real_scales))
            minimum, maximum = activation_range(output, node.options.fused_activation)
            p = {
                "input_zero_point": zero,
                "filter_zero_point": 0,
                "output_zero_point": out_zero,
                "output_activation_min": minimum,
                "output_activation_max": maximum,
            }
            if kind == "FULLY_CONNECTED":
                p.update(output_multiplier=multipliers[0], output_shift=shifts[0])
            else:
                p.update(
                    _padding(node), multipliers=list(multipliers), shifts=list(shifts)
                )
                policy = "skip invalid taps; input quantized zero for explicit padding; no full-filter bias correction"
            raw = graph.constant_values(weights.index)
            if kind == "DEPTHWISE_CONV_2D":
                rows = [raw[c::channels] for c in range(channels)]
            else:
                width = len(raw) // channels
                rows = [raw[c * width : (c + 1) * width] for c in range(channels)]
            bias_id = node.input("bias")
            biases = (
                graph.constant_values(bias_id)
                if bias_id is not None
                else (0,) * channels
            )
            # Bounds cover partial sums as well as bias addition and every legal INT8 input.
            input_max = max(abs(-128 - zero), abs(127 - zero))
            bounds = tuple(
                input_max * sum(abs(w) for w in row) + abs(b)
                for row, b in zip(rows, biases)
            )
            for bound, multiplier, shift in zip(
                bounds,
                multipliers * (channels if len(multipliers) == 1 else 1),
                shifts * (channels if len(shifts) == 1 else 1),
            ):
                i32(bound * (1 << max(shift, 0)))
                i32(abs(requantize(bound, multiplier, shift)) + abs(out_zero))
            if (
                kind == "CONV_2D"
                and weights.shape[1:3] == (1, 1)
                and not any(asdict(node.padding).values())
            ):
                corrections = tuple(
                    adjusted_bias(row, -zero, b) for row, b in zip(rows, biases)
                )
                for row, b in zip(rows, corrections):
                    i32(128 * sum(abs(w) for w in row) + abs(b))
                policy = "unpadded 1x1: corrected bias permitted; checked INT32 dot and corrected-bias prefixes"
        elif kind == "ADD":
            second = inputs[1].quantization
            twice_max = 2 * max(scale, second.scales[0])
            a, ash = quantize_multiplier(scale / twice_max)
            b, bsh = quantize_multiplier(second.scales[0] / twice_max)
            m, sh = quantize_multiplier(twice_max / ((1 << 20) * out_scale))
            if max(ash, bsh, sh) > 0:
                raise ModelError(
                    f"node {node.index}: ADD requires multipliers smaller than one"
                )
            minimum, maximum = activation_range(output, node.options.fused_activation)
            p = {
                "requires_broadcast": 0,
                "left_shift": 20,
                "input1_offset": -zero,
                "input2_offset": -second.zero_points[0],
                "output_offset": out_zero,
                "input1_multiplier": a,
                "input1_shift": ash,
                "input2_multiplier": b,
                "input2_shift": bsh,
                "output_multiplier": m,
                "output_shift": sh,
                "output_activation_min": minimum,
                "output_activation_max": maximum,
            }
            for x in (-128, 127):
                for y in (-128, 127):
                    add_scalar(x, y, p)
        elif kind == "AVERAGE_POOL_2D":
            minimum, maximum = activation_range(output, node.options.fused_activation)
            p = dict(_padding(node), activation_min=minimum, activation_max=maximum)
            i32(129 * node.options.filter_h * node.options.filter_w)
            policy = "skip invalid taps; divide by valid count; never count quantized-zero padding"
        elif kind == "QUANTIZE":
            m, sh = quantize_multiplier(scale / out_scale)
            p = {
                "input_zero_point": zero,
                "output_zero_point": out_zero,
                "requantize_output_multiplier": m,
                "requantize_output_shift": sh,
            }
        elif kind == "SOFTMAX":
            real = min(node.options.beta * scale * (1 << 26), float(I32_MAX))
            if real <= 1:
                raise ModelError("Softmax scaling must be greater than one")
            m, sh = quantize_multiplier(real)
            p = {
                "input_multiplier": m,
                "input_left_shift": sh,
                "diff_min": -math.floor(31 * (1 << 26) / (1 << sh)),
            }
            i32(source.shape[-1] * (1 << 19))
        elif kind != "RESHAPE":
            raise ModelError(
                f"node {node.index}: missing arithmetic contract for {kind}"
            )
        prepared.append(
            PreparedNode(
                node.index,
                kind,
                p,
                offsets,
                out_zero,
                bias_scales,
                bounds,
                corrections,
                policy,
            )
        )
    return PreparedGraph(graph.sha256, graph.model_sha256, tuple(prepared))


def compare_prepared(prepared: PreparedGraph, records: list[dict]) -> int:
    """Compare complete key sets, node identity, and every integer/array element."""
    expected = [
        {"node": node.node, "kind": node.kind, "integers": node.integers}
        for node in prepared.nodes
    ]
    if len(records) != len(expected):
        raise ModelError("prepared oracle node count differs")
    count = 0
    for reference, candidate in zip(records, expected):
        if reference != candidate:
            raise ModelError(
                f"prepared parameters diverge at node {candidate['node']}: expected {reference}, got {candidate}"
            )
        count += sum(
            len(v) if isinstance(v, list) else 1 for v in reference["integers"].values()
        )
    return count
