"""Stage 4 A0 lowering: validate the existing contracts, select only reference calls."""

from dataclasses import dataclass, field

from .compilation import CompilationContext
from .ir import Graph
from .kernel_plan import (
    KernelMemoryPlan,
    KernelPlan,
    require,
    select_reference_kernels,
    validate_kernel_plan,
)
from .memory_plan import MemoryPlan, plan_memory, validate_memory_plan
from .quantization import PreparedGraph


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
) -> LoweredModel:
    context = CompilationContext(graph)
    prepared = context.prepared if prepared is None else prepared
    context.check(graph, prepared)
    if kernels is None:
        kernels = select_reference_kernels(graph, prepared)
    else:
        validate_kernel_plan(kernels, graph, prepared)
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
        "A0 supports only the proven reference memory contracts",
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
