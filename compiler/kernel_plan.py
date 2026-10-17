"""Stage 3 kernel memory contracts; no optimized kernel selection or codegen.

The supported reference INT8 paths use scalar locals and no arena scratch.
INT4 unpacking, compression, optimized backends and INT16 Softmax LUTs are not
part of this contract. Stack *peak* requires a compiled Stage 4 call graph.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass

from .ir import REFERENCE_REVISION, Graph, ModelError
from .validation import validate_graph

REFERENCE_BACKEND = "pinned_reference_integer_rv64imc"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelError(message)


def alignment(value: int) -> int:
    require(
        type(value) is int and value > 0 and value & (value - 1) == 0,
        f"alignment must be a positive power of two: {value}",
    )
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
            json.dumps(asdict(self), sort_keys=True, indent=2, allow_nan=False) + "\n"
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
            json.dumps(asdict(self), sort_keys=True, indent=2, allow_nan=False) + "\n"
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    @classmethod
    def from_json(cls, text, graph, prepared):
        expected = select_reference_kernels(graph, prepared)
        require(
            json.loads(text) == json.loads(expected.to_json()),
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
    expected = select_reference_kernels(graph, prepared)
    require(
        plan == expected,
        "kernel plan differs from supported implementations or static facts",
    )


def reference_memory_contracts(graph: Graph) -> KernelMemoryPlan:
    validate_graph(graph)
    nodes = []
    for node in graph.nodes:
        inputs = tuple(
            OperandMemory(
                o.name,
                4
                if o.tensor is not None and graph.tensors[o.tensor].dtype == "INT32"
                else 1,
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
