"""Validated reference and scalar pointwise selections and memory contracts.

The supported reference INT8 paths use scalar locals and no arena scratch.
INT4 unpacking, compression and INT16 Softmax LUTs are not
part of this contract. Stack *peak* requires a compiled Stage 4 call graph.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace

from .ir import REFERENCE_REVISION, Graph, ModelError
from .validation import validate_graph
from .xrequant import optimization_options
from .depthwise import zero_policy
from .xpostinc import depthwise_policy as xpostinc_depthwise_policy
from .project_runtime import RUNTIMES, apply_runtime, runtime_mode, saved_runtime
from .requantization import (
    REQUANTIZATIONS,
    apply_requantization,
    requantization_mode,
    saved_requantization,
    requantization_overrides,
    saved_requantization_overrides,
)

REFERENCE_BACKEND = "pinned_reference_integer_rv64imc"
B1_POINTWISE = "rv64imc/pointwise_dot8/int8"
POINTWISE_KERNELS = {
    (1, 1): B1_POINTWISE,
    (1, 2): "rv64imc/pointwise_dot8_oc2/int8",
    (1, 4): "rv64imc/pointwise_dot8_oc4/int8",
    (2, 2): "rv64imc/pointwise_dot8_spatial2_oc2/int8",
    (2, 4): "rv64imc/pointwise_dot8_spatial2_oc4/int8",
}
POINTWISE_BLOCKS = {
    implementation: channels
    for (_, channels), implementation in POINTWISE_KERNELS.items()
}
SPATIAL_POINTWISE = {
    channels: implementation
    for (pixels, channels), implementation in POINTWISE_KERNELS.items()
    if pixels == 2
}
DEPTHWISE_KERNELS = {
    3: "rv64imc/depthwise_3x3/int8",
    5: "rv64imc/depthwise_5x5/int8",
}
STEM_UNROLL_CHOICE = "gcc_rv64_function_unroll_loops"
XQMAC8_WEIGHT_ALIGNMENT_CHOICE = "xqmac8_weight_alignment_8"
XQMAC8_ACCUMULATOR_CHOICE = "xqmac8_register_accumulator_64"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelError(message)


def alignment(value: int) -> int:
    require(
        type(value) is int and value > 0 and value & (value - 1) == 0,
        f"alignment must be a positive power of two: {value}",
    )
    return value


def serialized_plan(value):
    """Omit the default optional parameter format to preserve pre-X2 JSON."""
    if isinstance(value, dict):
        return {
            k: serialized_plan(v)
            for k, v in value.items()
            if not (
                (k == "parameter_format" and v == "int32")
                or (
                    k
                    in (
                        "depthwise_biases",
                        "depthwise_regions",
                        "stem_biases",
                        "stem_regions",
                        "stem_weights",
                    )
                    and not v
                )
            )
        }
    if isinstance(value, (list, tuple)):
        return [serialized_plan(v) for v in value]
    return value


@dataclass(frozen=True)
class OperandMemory:
    role: str
    alignment: int
    access: str = "read_only"


@dataclass(frozen=True)
class ScratchRequirement:
    name: str
    size_bytes: int
    alignment: int = 16
    enabled: bool = True
    condition: str = "always"
    # Arena scratch is node-local and cannot escape the call. Persistent
    # temporaries need a different contract; they must not masquerade as scratch.


@dataclass(frozen=True)
class KernelMemoryContract:
    node: int
    kind: str
    implementation: str
    inputs: tuple[OperandMemory, ...]
    output_alignments: tuple[int, ...]
    scratch: tuple[ScratchRequirement, ...] = ()
    reshape_view: bool = False
    parameter_format: str = "int32"
    depthwise_biases: tuple[int, ...] = ()
    depthwise_regions: tuple[int, ...] = ()
    stem_biases: tuple[int, ...] = ()
    stem_regions: tuple[int, ...] = ()
    stem_weights: tuple[int, ...] = ()
    stack_policy: str = (
        "fixed scalar locals and rank<=4 RuntimeShape; peak pending Stage 4 build"
    )


@dataclass(frozen=True)
class KernelMemoryPlan:
    graph_ir_sha256: str
    nodes: tuple[KernelMemoryContract, ...]
    reference_revision: str = REFERENCE_REVISION
    schema_version: int = 1

    def to_json(self) -> str:
        return (
            json.dumps(
                serialized_plan(asdict(self)), sort_keys=True, indent=2, allow_nan=False
            )
            + "\n"
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()


@dataclass(frozen=True)
class KernelGeometry:
    input_shape: tuple[int, ...]
    output_shape: tuple[int, ...]
    weight_shape: tuple[int, ...] = ()
    stride: tuple[int, int] = (1, 1)
    dilation: tuple[int, int] = (1, 1)
    padding: tuple[int, int, int, int] = (0, 0, 0, 0)
    groups: int = 1
    depth_multiplier: int = 1
    reduction_depth: int = 0
    dot8_tail: int = 0


@dataclass(frozen=True)
class KernelSelection:
    node: int
    kind: str
    implementation: str
    arithmetic_backend: str
    reduction_backend: str
    requantization_backend: str
    geometry: KernelGeometry
    scalar_parameters: tuple[tuple[str, int], ...]
    weight_layout: str
    corrected_bias_eligible: bool
    nonpositive_shifts: bool
    choices: tuple[str, ...]
    memory: KernelMemoryContract


@dataclass(frozen=True)
class KernelPlan:
    graph_ir_sha256: str
    prepared_ir_sha256: str
    nodes: tuple[KernelSelection, ...]
    configuration: str = "A0"
    schema_version: int = 1

    @property
    def memory_contracts(self) -> KernelMemoryPlan:
        return KernelMemoryPlan(
            self.graph_ir_sha256, tuple(n.memory for n in self.nodes)
        )

    def to_json(self) -> str:
        return (
            json.dumps(
                serialized_plan(asdict(self)), sort_keys=True, indent=2, allow_nan=False
            )
            + "\n"
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    @classmethod
    def from_json(cls, text, graph, prepared):
        data = json.loads(text)
        expected = select_kernels(
            graph,
            prepared,
            data.get("configuration"),
            **optimization_options(data["nodes"]),
            depthwise_zero_point=zero_policy(data["nodes"]),
            xpostinc_depthwise=xpostinc_depthwise_policy(data["nodes"]),
            xqmac8_accumulator_bits=(
                64
                if any(XQMAC8_ACCUMULATOR_CHOICE in n["choices"] for n in data["nodes"])
                else 32
            ),
            xqmac8_weight_alignment=(
                8
                if any(
                    XQMAC8_WEIGHT_ALIGNMENT_CHOICE in n["choices"]
                    for n in data["nodes"]
                )
                else 4
            ),
            runtime=saved_runtime(data["nodes"]),
            requantization=saved_requantization(data["nodes"]),
            requantization_overrides=saved_requantization_overrides(data["nodes"]),
            depthwise_kernels=tuple(
                k
                for k, impl in DEPTHWISE_KERNELS.items()
                if any(n["implementation"] == impl for n in data["nodes"])
            ),
            stem_unroll=any(STEM_UNROLL_CHOICE in n["choices"] for n in data["nodes"]),
            pointwise_blocks={
                n["node"]: POINTWISE_BLOCKS[n["implementation"]]
                for n in data["nodes"]
                if n["implementation"] in POINTWISE_BLOCKS
            },
            pointwise_tiles={
                n["node"]: (2, POINTWISE_BLOCKS[n["implementation"]])
                for n in data["nodes"]
                if n["implementation"] in SPATIAL_POINTWISE.values()
            },
        )
        require(
            data == json.loads(expected.to_json()),
            "saved kernel plan differs from supported implementations or static facts",
        )
        return expected


def select_reference_kernels(graph: Graph, prepared) -> KernelPlan:
    """Select implemented kernels and record facts for later B1/X1 eligibility."""
    contracts = reference_memory_contracts(graph)
    selections = []
    for node, params, memory in zip(graph.nodes, prepared.nodes, contracts.nodes):
        source = graph.tensors[node.inputs[0].tensor]
        output = graph.tensors[node.outputs[0]]
        weighted = node.kind in ("CONV_2D", "DEPTHWISE_CONV_2D", "FULLY_CONNECTED")
        weights = graph.tensors[node.input("weights")] if weighted else None
        depth = (
            (
                math.prod(weights.shape[1:3])
                if node.kind == "DEPTHWISE_CONV_2D"
                else math.prod(weights.shape[1:])
            )
            if weights
            else 0
        )
        opts = node.options
        if node.kind == "SOFTMAX":
            require(
                source.shape[-1] <= 1000,
                f"node {node.index}: cc_softmax supports depth <= 1000",
            )
            p = params.integers
            require(
                0 <= p["input_left_shift"] <= 30
                and p["input_multiplier"] > 0
                and p["diff_min"] <= 0,
                f"node {node.index}: invalid static cc_softmax parameters",
            )
        geometry = KernelGeometry(
            source.shape,
            output.shape,
            weights.shape if weights else (),
            (getattr(opts, "stride_h", 1), getattr(opts, "stride_w", 1)),
            (getattr(opts, "dilation_h", 1), getattr(opts, "dilation_w", 1)),
            tuple(asdict(node.padding).values()) if node.padding else (0, 0, 0, 0),
            depth_multiplier=getattr(opts, "depth_multiplier", 1),
            reduction_depth=depth,
            dot8_tail=depth % 8,
        )
        shifts = params.integers.get("shifts", [])
        selections.append(
            KernelSelection(
                node.index,
                node.kind,
                memory.implementation,
                REFERENCE_BACKEND,
                "reference_scalar",
                "reference_double_rounding",
                geometry,
                tuple(
                    (k, v) for k, v in sorted(params.integers.items()) if type(v) is int
                ),
                weights.layout if weights else "none",
                params.adjusted_biases is not None,
                bool(shifts) and all(s <= 0 for s in shifts),
                ("explicit_shapes", "scalar_literals"),
                memory,
            )
        )
    return KernelPlan(graph.sha256, prepared.sha256, tuple(selections))


def validate_kernel_plan(plan: KernelPlan, graph: Graph, prepared) -> None:
    # Only implemented selections are accepted. Unknown backends cannot acquire
    # a reference fallback or a misleading profile label by changing metadata.
    expected = select_kernels(
        graph,
        prepared,
        plan.configuration,
        **optimization_options(plan.nodes),
        depthwise_zero_point=zero_policy(plan.nodes),
        xpostinc_depthwise=xpostinc_depthwise_policy(plan.nodes),
        xqmac8_weight_alignment=xqmac8_weight_alignment(plan),
        xqmac8_accumulator_bits=xqmac8_accumulator_bits(plan),
        runtime=runtime_mode(plan),
        requantization=requantization_mode(plan),
        requantization_overrides=requantization_overrides(plan),
        stem_unroll=uses_stem_unroll(plan),
        depthwise_kernels=selected_depthwise_kernels(plan),
        pointwise_blocks={
            n.node: pointwise_block_size(n)
            for n in plan.nodes
            if pointwise_block_size(n)
        },
        pointwise_tiles=selected_pointwise_tiles(plan),
    )
    require(
        plan == expected,
        "kernel plan differs from supported implementations or static facts",
    )


def uses_stem_unroll(plan: KernelPlan) -> bool:
    return any(STEM_UNROLL_CHOICE in n.choices for n in plan.nodes)


def xqmac8_weight_alignment(plan: KernelPlan) -> int:
    return (
        8 if any(XQMAC8_WEIGHT_ALIGNMENT_CHOICE in n.choices for n in plan.nodes) else 4
    )


def xqmac8_accumulator_bits(plan: KernelPlan) -> int:
    return 64 if any(XQMAC8_ACCUMULATOR_CHOICE in n.choices for n in plan.nodes) else 32


def pointwise_block_size(selection: KernelSelection) -> int:
    """Zero is another kernel family; 1/2/4 are implemented schedules."""
    return POINTWISE_BLOCKS.get(selection.implementation, 0)


def pointwise_pixels(selection: KernelSelection) -> int:
    if selection.implementation in SPATIAL_POINTWISE.values():
        return 2
    return 1 if pointwise_block_size(selection) else 0


def selected_pointwise_tiles(plan: KernelPlan) -> dict[int, tuple[int, int]]:
    return {
        n.node: (2, pointwise_block_size(n))
        for n in plan.nodes
        if pointwise_pixels(n) == 2
    }


def validate_pointwise_request(
    plan, graph, prepared, *, block=None, pixels=None, tiles=None
):
    """Check explicit requests without discarding a saved orthogonal policy."""
    if block is None and pixels is None and tiles is None:
        return
    spatial = selected_pointwise_tiles(plan)
    if tiles is None:
        # A supplied global pixel count replaces the saved spatial schedule.
        # A channel-only request preserves pixel tiling but replaces channels.
        tiles = (
            {}
            if pixels is not None
            else {
                n: (p, c if block is None else block) for n, (p, c) in spatial.items()
            }
        )
    expected = select_kernels(
        graph,
        prepared,
        plan.configuration,
        **optimization_options(plan.nodes),
        depthwise_zero_point=zero_policy(plan.nodes),
        xpostinc_depthwise=xpostinc_depthwise_policy(plan.nodes),
        xqmac8_weight_alignment=xqmac8_weight_alignment(plan),
        xqmac8_accumulator_bits=xqmac8_accumulator_bits(plan),
        runtime=runtime_mode(plan),
        requantization=requantization_mode(plan),
        requantization_overrides=requantization_overrides(plan),
        stem_unroll=uses_stem_unroll(plan),
        depthwise_kernels=selected_depthwise_kernels(plan),
        pointwise_block=1 if block is None else block,
        pointwise_blocks=(
            {
                n.node: pointwise_block_size(n)
                for n in plan.nodes
                if pointwise_block_size(n)
            }
            if block is None
            else {}
        ),
        pointwise_pixels=1 if pixels is None else pixels,
        pointwise_tiles=tiles,
    )
    label = (
        "block" if block is not None else "pixels" if pixels is not None else "tiles"
    )
    require(
        plan == expected,
        f"supplied kernel plan differs from requested pointwise {label}",
    )


def depthwise_filter_size(selection: KernelSelection) -> int:
    return next(
        (
            k
            for k, impl in DEPTHWISE_KERNELS.items()
            if selection.implementation == impl
        ),
        0,
    )


def selected_depthwise_kernels(plan: KernelPlan) -> tuple[int, ...]:
    return tuple(sorted({k for n in plan.nodes if (k := depthwise_filter_size(n))}))


def depthwise_eligible(selection: KernelSelection, size: int) -> bool:
    g = selection.geometry
    return (
        selection.kind == "DEPTHWISE_CONV_2D"
        and g.weight_shape == (1, size, size, g.input_shape[-1])
        and g.depth_multiplier == 1
        and g.dilation == (1, 1)
        and all(s in (1, 2) for s in g.stride)
        and g.input_shape[0] == g.output_shape[0]
        and g.input_shape[-1] == g.output_shape[-1]
    )


def stem_unroll_eligible(selection: KernelSelection) -> bool:
    """Measured RGB 3x3 stride-two reference path; no node-number selection."""
    g = selection.geometry
    return (
        selection.kind == "CONV_2D"
        and g.weight_shape[1:] == (3, 3, 3)
        and g.stride == (2, 2)
        and g.dilation == (1, 1)
        and g.groups == 1
    )


def select_kernels(
    graph: Graph,
    prepared,
    configuration: str = "A0",
    *,
    stem_unroll: bool = False,
    pointwise_block: int = 1,
    pointwise_blocks: dict[int, int] | None = None,
    pointwise_pixels: int = 1,
    pointwise_tiles: dict[int, tuple[int, int]] | None = None,
    depthwise_kernels: tuple[int, ...] = (),
    runtime: str = "reference",
    requantization: str = "generic",
    requantization_overrides: dict[int, str] | None = None,
    xqmac8_weight_alignment: int = 4,
    xqmac8_accumulator_bits: int = 32,
    xrequant_depthwise_outlining: str = "none",
    xrequant_add_register_bits: int = 32,
    xpostinc_depthwise: str = "all",
    depthwise_zero_point: str = "none",
) -> KernelPlan:
    """Explicit implemented configurations; checkpoint labels never select code."""
    if configuration in ("X3", "X4", "X5"):
        from .xpostinc import select_x3

        require(
            xqmac8_weight_alignment == 8, "X3 requires 8-byte packed weight alignment"
        )
        parent = select_x3(
            select_kernels(
                graph,
                prepared,
                "X2",
                stem_unroll=stem_unroll,
                pointwise_block=pointwise_block,
                pointwise_blocks=pointwise_blocks,
                pointwise_pixels=pointwise_pixels,
                pointwise_tiles=pointwise_tiles,
                depthwise_kernels=depthwise_kernels,
                runtime=runtime,
                requantization=requantization,
                requantization_overrides=requantization_overrides,
                xqmac8_weight_alignment=xqmac8_weight_alignment,
                xqmac8_accumulator_bits=xqmac8_accumulator_bits,
                xrequant_depthwise_outlining=xrequant_depthwise_outlining,
                xrequant_add_register_bits=xrequant_add_register_bits,
            ),
            depthwise=xpostinc_depthwise,
        )
        from .depthwise import select_depthwise

        result = select_depthwise(
            parent,
            graph,
            prepared,
            zero=depthwise_zero_point,
            bank=configuration in ("X4", "X5"),
        )
        if configuration == "X5":
            from .stem import select_stem

            return select_stem(result, graph, prepared)
        return result
    require(
        depthwise_zero_point == "none", "depthwise zero-point hoisting requires X3/X4"
    )
    require(xpostinc_depthwise == "all", "post-increment depthwise policies require X3")
    require(
        xrequant_depthwise_outlining in ("none", "selected"),
        "invalid Xrequant depthwise outlining policy",
    )
    require(
        type(xrequant_add_register_bits) is int
        and xrequant_add_register_bits in (32, 64),
        "Xrequant ADD register size must be 32 or 64",
    )
    require(
        configuration == "X2"
        or (
            xrequant_depthwise_outlining == "none" and xrequant_add_register_bits == 32
        ),
        "Xrequant optimizations require X2",
    )
    require(
        type(xqmac8_weight_alignment) is int and xqmac8_weight_alignment in (4, 8),
        "Xqmac8 weight alignment must be 4 or 8",
    )
    require(
        configuration in ("X1", "X2") or xqmac8_weight_alignment == 4,
        "packed weight alignment requires X1",
    )
    require(
        type(xqmac8_accumulator_bits) is int and xqmac8_accumulator_bits in (32, 64),
        "Xqmac8 accumulator register size must be 32 or 64",
    )
    require(
        configuration in ("X1", "X2") or xqmac8_accumulator_bits == 32,
        "wide accumulator registers require X1",
    )
    if configuration == "X2":
        from .xrequant import select_x2

        parent = select_kernels(
            graph,
            prepared,
            "X1",
            stem_unroll=stem_unroll,
            pointwise_block=pointwise_block,
            pointwise_blocks=pointwise_blocks,
            pointwise_pixels=pointwise_pixels,
            pointwise_tiles=pointwise_tiles,
            depthwise_kernels=depthwise_kernels,
            runtime=runtime,
            requantization=requantization,
            requantization_overrides=requantization_overrides,
            xqmac8_weight_alignment=xqmac8_weight_alignment,
            xqmac8_accumulator_bits=xqmac8_accumulator_bits,
        )
        return select_x2(
            parent,
            graph,
            prepared,
            depthwise_outlining=xrequant_depthwise_outlining,
            add_register_bits=xrequant_add_register_bits,
        )
    if configuration == "X1":
        software = select_kernels(
            graph,
            prepared,
            "B1",
            stem_unroll=stem_unroll,
            pointwise_block=pointwise_block,
            pointwise_blocks=pointwise_blocks,
            pointwise_pixels=pointwise_pixels,
            pointwise_tiles=pointwise_tiles,
            depthwise_kernels=depthwise_kernels,
            runtime=runtime,
            requantization=requantization,
            requantization_overrides=requantization_overrides,
        )
        require(
            any(pointwise_block_size(n) for n in software.nodes),
            "X1 requires an eligible pointwise dot8 kernel",
        )
        return replace(
            software,
            configuration="X1",
            nodes=tuple(
                replace(
                    n,
                    reduction_backend="xqmac8_spatial2"
                    if n.implementation in SPATIAL_POINTWISE.values()
                    else "xqmac8",
                    arithmetic_backend="xqmac8_int32_reference_quantization",
                    choices=(
                        *n.choices,
                        "xqmac8_v1",
                        *(
                            (XQMAC8_WEIGHT_ALIGNMENT_CHOICE,)
                            if xqmac8_weight_alignment == 8
                            else ()
                        ),
                        *(
                            (XQMAC8_ACCUMULATOR_CHOICE,)
                            if xqmac8_accumulator_bits == 64
                            else ()
                        ),
                    ),
                    memory=(
                        replace(
                            n.memory,
                            inputs=tuple(
                                replace(operand, alignment=8)
                                if operand.role == "weights"
                                else operand
                                for operand in n.memory.inputs
                            ),
                        )
                        if xqmac8_weight_alignment == 8
                        else n.memory
                    ),
                )
                if pointwise_block_size(n)
                else n
                for n in software.nodes
            ),
        )
    require(runtime in RUNTIMES, "unsupported runtime library")
    require(requantization in REQUANTIZATIONS, "unsupported requantization policy")
    quant_overrides = (
        {} if requantization_overrides is None else requantization_overrides
    )
    require(
        isinstance(quant_overrides, dict)
        and all(
            type(n) is int and mode in REQUANTIZATIONS[1:]
            for n, mode in quant_overrides.items()
        ),
        "invalid requantization overrides",
    )
    require(
        (requantization == "generic" and not quant_overrides)
        or (configuration == "B1" and runtime != "reference"),
        "requantization specialization requires project B1 arithmetic",
    )
    require(
        configuration == "B1" or runtime == "reference", "project runtime requires B1"
    )
    require(configuration in ("A0", "B1"), "unsupported kernel configuration")
    require(type(stem_unroll) is bool, "stem_unroll must be a boolean")
    require(not stem_unroll or configuration == "B1", "stem unrolling requires B1")
    require(
        type(pointwise_block) is int and pointwise_block in (1, 2, 4),
        "pointwise block must be 1, 2 or 4",
    )
    overrides = {} if pointwise_blocks is None else pointwise_blocks
    tiles = {} if pointwise_tiles is None else pointwise_tiles
    require(
        type(pointwise_pixels) is int and pointwise_pixels in (1, 2),
        "pointwise pixels must be 1 or 2",
    )
    require(
        isinstance(tiles, dict)
        and all(
            type(n) is int
            and isinstance(t, tuple)
            and len(t) == 2
            and all(type(v) is int for v in t)
            and (t[0] == 1 and t[1] in (1, 2, 4) or t[0] == 2 and t[1] in (2, 4))
            for n, t in tiles.items()
        ),
        "invalid pointwise tiles",
    )
    require(
        pointwise_pixels == 1 or pointwise_block in (2, 4) or bool(overrides),
        "two-pixel pointwise tiles require output-channel blocks 2 or 4",
    )
    require(
        configuration == "B1" or (pointwise_pixels == 1 and not tiles),
        "spatial pointwise blocking requires B1",
    )
    require(
        isinstance(overrides, dict)
        and all(
            type(n) is int and type(b) is int and b in (1, 2, 4)
            for n, b in overrides.items()
        ),
        "invalid pointwise block overrides",
    )
    require(
        configuration == "B1" or (pointwise_block == 1 and not overrides),
        "pointwise blocking requires B1",
    )
    require(
        isinstance(depthwise_kernels, tuple)
        and all(type(k) is int and k in DEPTHWISE_KERNELS for k in depthwise_kernels)
        and len(set(depthwise_kernels)) == len(depthwise_kernels),
        "depthwise kernels must be distinct filter sizes 3 or 5",
    )
    require(
        not depthwise_kernels or configuration == "B1", "depthwise kernels require B1"
    )
    reference = select_reference_kernels(graph, prepared)
    if configuration == "A0":
        return reference
    nodes = []
    eligible_nodes = set()
    for selection, params in zip(reference.nodes, prepared.nodes):
        g = selection.geometry
        eligible = (
            selection.kind == "CONV_2D"
            and g.weight_shape[1:3] == (1, 1)
            and g.stride == g.dilation == (1, 1)
            and not any(g.padding)
            and g.input_shape[:3] == g.output_shape[:3]
            and g.reduction_depth % 8 == 0
            and selection.corrected_bias_eligible
        )
        if eligible:
            eligible_nodes.add(selection.node)
            pixels, requested = tiles.get(
                selection.node,
                (pointwise_pixels, overrides.get(selection.node, pointwise_block)),
            )
            block = requested if g.output_shape[-1] % requested == 0 else 1
            if block == 1:
                pixels = 1
            if pixels == 2:
                require(
                    block in (2, 4),
                    "two-pixel pointwise tiles require output-channel blocks 2 or 4",
                )
            implementation = POINTWISE_KERNELS[pixels, block]
            # Preparation proves abs(corrected_bias) + 128*sum(abs(weight))
            # fits INT32: bias-first accumulation and every dot8 prefix are safe.
            require(params.adjusted_biases is not None, "missing corrected biases")
            selection = replace(
                selection,
                implementation=implementation,
                arithmetic_backend="scalar_rv64imc_reference_quantization",
                reduction_backend=(
                    "scalar_dot8_spatial2" if pixels == 2 else "scalar_dot8"
                ),
                choices=(
                    "corrected_bias",
                    "pointer_rows",
                    "reduction_unroll_8",
                    f"output_channel_tile_{block}",
                    *(
                        (
                            "spatial_pixel_tile_2",
                            "weights_shared_across_pixels",
                            (
                                "odd_pixel_tail_single_pixel"
                                if math.prod(g.output_shape[:3]) % 2
                                else "no_spatial_tail"
                            ),
                        )
                        if pixels == 2
                        else ()
                    ),
                ),
                memory=replace(
                    selection.memory,
                    implementation=implementation,
                    stack_policy=(
                        f"fixed {2 * block} scalar accumulators and pointers; no scratch"
                        if pixels == 2
                        else (
                            "fixed scalar accumulator and pointers; no scratch"
                            if block == 1
                            else f"fixed {block} scalar accumulators and pointers; no scratch"
                        )
                    ),
                ),
            )
        for size in depthwise_kernels:
            if depthwise_eligible(selection, size):
                implementation = DEPTHWISE_KERNELS[size]
                selection = replace(
                    selection,
                    implementation=implementation,
                    arithmetic_backend="scalar_rv64imc_reference_quantization",
                    reduction_backend="scalar_depthwise_valid_taps",
                    choices=(
                        "fixed_filter_dimensions",
                        "constant_nhwc_strides",
                        "interior_border_split",
                        "interior_tap_unroll",
                        "border_clip_per_pixel",
                        "reference_input_offset",
                    ),
                    memory=replace(
                        selection.memory,
                        implementation=implementation,
                        stack_policy="fixed scalar accumulator and pointers; no scratch",
                    ),
                )
        if stem_unroll and stem_unroll_eligible(selection):
            selection = replace(
                selection, choices=(*selection.choices, STEM_UNROLL_CHOICE)
            )
        nodes.append(selection)
    result = replace(
        reference,
        nodes=apply_requantization(
            apply_runtime(graph, nodes, runtime),
            prepared,
            requantization,
            quant_overrides,
        ),
        configuration="B1",
    )
    require(
        set(overrides) <= eligible_nodes,
        "pointwise block override targets an unsupported kernel",
    )
    require(
        set(tiles) <= eligible_nodes,
        "pointwise tile override targets an unsupported kernel",
    )
    require(
        not stem_unroll or uses_stem_unroll(result),
        "stem unrolling requires a supported RGB 3x3 stride-two convolution",
    )
    return result


def parameter_values(prepared_node, contract: KernelMemoryContract) -> dict:
    """The same selected payload drives constant allocation and emission."""
    values = dict(prepared_node.integers)
    if contract.implementation in POINTWISE_BLOCKS:
        require(prepared_node.adjusted_biases is not None, "missing corrected biases")
        values["corrected_biases"] = list(prepared_node.adjusted_biases)
    if contract.depthwise_biases:
        values["depthwise_biases"] = list(contract.depthwise_biases)
        values["depthwise_regions"] = list(contract.depthwise_regions)
    if contract.stem_weights:
        values["stem_weights"] = list(contract.stem_weights)
        values["stem_biases"] = list(contract.stem_biases)
        values["stem_regions"] = list(contract.stem_regions)
    if contract.parameter_format == "xrequant_v1":
        from .xrequant import packed_words

        values["xrequant_descriptors"] = packed_words(prepared_node)
        values.pop("multipliers", None)
        values.pop("shifts", None)
    return values


def reference_memory_contracts(graph: Graph) -> KernelMemoryPlan:
    validate_graph(graph)
    nodes = []
    for node in graph.nodes:
        inputs = tuple(
            OperandMemory(
                o.name,
                (
                    4
                    if o.tensor is not None and graph.tensors[o.tensor].dtype == "INT32"
                    else 1
                ),
            )
            for o in node.inputs
        )
        nodes.append(
            KernelMemoryContract(
                node.index,
                node.kind,
                f"pinned_reference/{node.kind.lower()}/int8",
                inputs,
                (1,),
                reshape_view=node.kind == "RESHAPE",
            )
        )
    result = KernelMemoryPlan(graph.sha256, tuple(nodes))
    validate_contracts(graph, result)
    return result


def validate_contracts(graph: Graph, contracts: KernelMemoryPlan) -> None:
    require(
        contracts.schema_version == 1
        and contracts.reference_revision == graph.reference_revision
        and contracts.graph_ir_sha256 == graph.sha256,
        "kernel memory contract provenance mismatch",
    )
    require(
        len(contracts.nodes) == len(graph.nodes),
        "kernel memory contract node count mismatch",
    )
    for node, contract in zip(graph.nodes, contracts.nodes):
        prefix = f"node {node.index} memory contract: "
        require(
            contract.parameter_format in ("int32", "xrequant_v1"),
            prefix + "unknown parameter format",
        )
        require(
            (contract.node, contract.kind) == (node.index, node.kind),
            prefix + "identity mismatch",
        )
        require(
            bool(contract.implementation) and bool(contract.stack_policy),
            prefix + "missing implementation/stack policy",
        )
        require(
            tuple(o.role for o in contract.inputs)
            == tuple(o.name for o in node.inputs),
            prefix + "input roles mismatch",
        )
        require(
            len(contract.output_alignments) == len(node.outputs),
            prefix + "output count mismatch",
        )
        for value in contract.output_alignments:
            alignment(value)
        for operand, memory in zip(node.inputs, contract.inputs):
            alignment(memory.alignment)
            require(
                memory.access in ("read_only", "read_write"),
                prefix + "unknown input access",
            )
            if (
                operand.tensor is not None
                and graph.tensors[operand.tensor].storage == "constant"
            ):
                require(
                    memory.access == "read_only",
                    prefix + "cannot mutate immutable operand",
                )
        require(
            type(contract.reshape_view) is bool
            and (not contract.reshape_view or node.kind == "RESHAPE"),
            prefix
            + "only Reshape has a proven view contract; ordinary in-place execution unsupported",
        )
        names = set()
        for scratch in contract.scratch:
            require(
                bool(scratch.name) and scratch.name not in names,
                prefix + "duplicate/empty scratch name",
            )
            names.add(scratch.name)
            alignment(scratch.alignment)
            require(
                type(scratch.size_bytes) is int and scratch.size_bytes >= 0,
                prefix + "invalid scratch size",
            )
            require(
                type(scratch.enabled) is bool and bool(scratch.condition),
                prefix + "scratch condition must be resolved offline",
            )
