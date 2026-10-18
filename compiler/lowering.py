"""Lower validated graphs into explicit reference or scalar B1 kernel plans."""

from dataclasses import dataclass, field

from .compilation import CompilationContext
from .ir import Graph
from .kernel_plan import (
    KernelMemoryPlan,
    KernelPlan,
    require,
    select_kernels,
    uses_stem_unroll,
    selected_depthwise_kernels,
    validate_kernel_plan,
    validate_pointwise_request,
    xqmac8_weight_alignment as selected_xqmac8_weight_alignment,
    xqmac8_accumulator_bits as selected_xqmac8_accumulator_bits,
)
from .memory_plan import MemoryPlan, plan_memory, validate_memory_plan
from .quantization import PreparedGraph
from .project_runtime import runtime_mode
from .xrequant import optimization_options
from .xpostinc import depthwise_policy
from .requantization import (
    requantization_mode,
    requantization_overrides as selected_requantization_overrides,
)


@dataclass(frozen=True)
class LoweredModel:
    graph: Graph
    prepared: PreparedGraph
    kernels: KernelPlan
    memory: MemoryPlan
    context: CompilationContext = field(repr=False, compare=False)

    @property
    def contracts(self) -> KernelMemoryPlan:
        return self.kernels.memory_contracts


def lower_graph(
    graph: Graph,
    prepared: PreparedGraph | None = None,
    memory: MemoryPlan | None = None,
    *,
    kernels: KernelPlan | None = None,
    configuration: str | None = None,
    stem_unroll: bool | None = None,
    pointwise_block: int | None = None,
    pointwise_pixels: int | None = None,
    pointwise_tiles: dict[int, tuple[int, int]] | None = None,
    depthwise_kernels: tuple[int, ...] | None = None,
    runtime: str | None = None,
    requantization: str | None = None,
    requantization_overrides: dict[int, str] | None = None,
    xqmac8_weight_alignment: int | None = None,
    xqmac8_accumulator_bits: int | None = None,
    xrequant_depthwise_outlining: str | None = None,
    xrequant_add_register_bits: int | None = None,
    xpostinc_depthwise: str | None = None,
) -> LoweredModel:
    context = CompilationContext(graph)
    prepared = context.prepared if prepared is None else prepared
    context.check(graph, prepared)
    if kernels is None:
        kernels = select_kernels(
            graph,
            prepared,
            configuration if configuration is not None else "A0",
            xpostinc_depthwise=xpostinc_depthwise or "all",
            xrequant_depthwise_outlining=xrequant_depthwise_outlining or "none",
            xrequant_add_register_bits=32
            if xrequant_add_register_bits is None
            else xrequant_add_register_bits,
            runtime="reference" if runtime is None else runtime,
            requantization="generic" if requantization is None else requantization,
            requantization_overrides=requantization_overrides,
            stem_unroll=False if stem_unroll is None else stem_unroll,
            pointwise_block=1 if pointwise_block is None else pointwise_block,
            pointwise_pixels=1 if pointwise_pixels is None else pointwise_pixels,
            pointwise_tiles=pointwise_tiles,
            xqmac8_weight_alignment=4
            if xqmac8_weight_alignment is None
            else xqmac8_weight_alignment,
            xqmac8_accumulator_bits=32
            if xqmac8_accumulator_bits is None
            else xqmac8_accumulator_bits,
            depthwise_kernels=() if depthwise_kernels is None else depthwise_kernels,
        )
    else:
        require(
            configuration is None or configuration == kernels.configuration,
            "supplied kernel plan configuration differs from lowering configuration",
        )
        validate_kernel_plan(kernels, graph, prepared)
        require(
            xpostinc_depthwise is None
            or xpostinc_depthwise == depthwise_policy(kernels.nodes),
            "supplied kernel plan differs from requested Xpostinc depthwise policy",
        )
        for name, requested in (
            ("xrequant_depthwise_outlining", xrequant_depthwise_outlining),
            ("xrequant_add_register_bits", xrequant_add_register_bits),
        ):
            require(
                requested is None
                or requested == optimization_options(kernels.nodes)[name],
                f"supplied kernel plan differs from requested {name}",
            )
        require(
            xqmac8_accumulator_bits is None
            or xqmac8_accumulator_bits == selected_xqmac8_accumulator_bits(kernels),
            "supplied kernel plan differs from requested Xqmac8 accumulator register size",
        )
        require(
            xqmac8_weight_alignment is None
            or xqmac8_weight_alignment == selected_xqmac8_weight_alignment(kernels),
            "supplied kernel plan differs from requested Xqmac8 weight alignment",
        )
        require(
            requantization is None or requantization == requantization_mode(kernels),
            "supplied kernel plan differs from requested requantization",
        )
        require(
            requantization_overrides is None
            or requantization_overrides == selected_requantization_overrides(kernels),
            "supplied kernel plan differs from requested requantization overrides",
        )
        require(
            runtime is None or runtime == runtime_mode(kernels),
            "supplied kernel plan differs from requested runtime",
        )
        require(
            stem_unroll is None
            or (type(stem_unroll) is bool and stem_unroll == uses_stem_unroll(kernels)),
            "supplied kernel plan differs from requested stem unrolling",
        )
        require(
            depthwise_kernels is None
            or depthwise_kernels == selected_depthwise_kernels(kernels),
            "supplied kernel plan differs from requested depthwise kernels",
        )
        validate_pointwise_request(
            kernels,
            graph,
            prepared,
            block=pointwise_block,
            pixels=pointwise_pixels,
            tiles=pointwise_tiles,
        )
    contracts = kernels.memory_contracts
    if memory is None:
        memory = plan_memory(graph, prepared, contracts, context=context)
    else:
        validate_memory_plan(memory, graph, prepared, contracts, context=context)
    _validate_interface(graph, memory, contracts)
    return LoweredModel(graph, prepared, kernels, memory, context)


def _validate_interface(graph, memory, contracts):
    require(
        len(graph.inputs) == len(graph.outputs) == 1,
        "A0 requires one public input/output",
    )
    require(
        all(
            t.dtype in ("INT8", "UINT8")
            for t in graph.tensors
            if t.storage == "runtime"
        ),
        "A0 runtime storage must consist of byte tensors",
    )
    require(
        graph.tensors[graph.inputs[0]].dtype
        == graph.tensors[graph.outputs[0]].dtype
        == "UINT8",
        "A0 preserves UINT8 public boundaries",
    )
    require(
        not memory.scratch and memory.kernel_memory_sha256 == contracts.sha256,
        "lowering supports only validated scratch-free kernel memory contracts",
    )


def validate_lowered_model(model: LoweredModel) -> None:
    """Check the supplied plan, never silently select a replacement during emission."""
    model.context.check(model.graph, model.prepared)
    validate_kernel_plan(model.kernels, model.graph, model.prepared)
    validate_memory_plan(
        model.memory,
        model.graph,
        model.prepared,
        model.contracts,
        context=model.context,
    )
    _validate_interface(model.graph, model.memory, model.contracts)
