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
)
from .memory_plan import MemoryPlan, plan_memory, validate_memory_plan
from .quantization import PreparedGraph
from .project_runtime import runtime_mode


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
    depthwise_kernels: tuple[int, ...] | None = None,
    runtime: str | None = None,
) -> LoweredModel:
    context = CompilationContext(graph)
    prepared = context.prepared if prepared is None else prepared
    context.check(graph, prepared)
    if kernels is None:
        kernels = select_kernels(
            graph,
            prepared,
            configuration if configuration is not None else "A0",
            runtime="reference" if runtime is None else runtime,
            stem_unroll=False if stem_unroll is None else stem_unroll,
            pointwise_block=1 if pointwise_block is None else pointwise_block,
            depthwise_kernels=() if depthwise_kernels is None else depthwise_kernels,
        )
    else:
        require(
            configuration is None or configuration == kernels.configuration,
            "supplied kernel plan configuration differs from lowering configuration",
        )
        validate_kernel_plan(kernels, graph, prepared)
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
        if pointwise_block is not None:
            require(
                kernels
                == select_kernels(
                    graph,
                    prepared,
                    kernels.configuration,
                    runtime=runtime_mode(kernels),
                    stem_unroll=uses_stem_unroll(kernels),
                    pointwise_block=pointwise_block,
                    depthwise_kernels=selected_depthwise_kernels(kernels),
                ),
                "supplied kernel plan differs from requested pointwise block",
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
