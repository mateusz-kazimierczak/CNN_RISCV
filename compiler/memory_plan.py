"""Deterministic static storage, inclusive node lifetimes and independent checks.

Epoch -1 is input setup, 0..N-1 are whole kernel calls, N is output handoff.
Input and output lifetimes overlap at a call; reuse requires end < start.
Only proven read-only Reshape views share an allocation while live.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace

from .compilation import CompilationContext
from .ir import TYPE_FORMATS, Graph, ModelError
from .kernel_plan import (
    KernelMemoryPlan,
    alignment,
    parameter_values,
    reference_memory_contracts,
    require,
    validate_contracts,
)
from .quantization import PreparedGraph
from .validation import validate_graph


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def align_up(value: int, multiple: int) -> int:
    alignment(multiple)
    return (value + multiple - 1) // multiple * multiple


@dataclass(frozen=True)
class BufferRequest:
    name: str
    size_bytes: int
    alignment: int
    start: int
    end: int
    category: str = "activation"


@dataclass(frozen=True)
class Placement:
    name: str
    offset: int | None


def live_overlap(a: BufferRequest, b: BufferRequest) -> bool:
    return a.start <= b.end and b.start <= a.end


def validate_requests(requests: tuple[BufferRequest, ...]) -> None:
    require(
        len({r.name for r in requests}) == len(requests),
        "duplicate buffer request identity",
    )
    for r in requests:
        require(
            bool(r.name) and type(r.size_bytes) is int and r.size_bytes >= 0,
            "invalid buffer name/size",
        )
        alignment(r.alignment)
        require(
            type(r.start) is int and type(r.end) is int and -1 <= r.start <= r.end,
            "invalid buffer lifetime",
        )
        require(r.category in ("activation", "scratch"), "invalid buffer category")


def first_fit(requests: tuple[BufferRequest, ...]) -> tuple[Placement, ...]:
    """Largest first, then lifetime/identity; lowest fitting aligned byte offset."""
    validate_requests(requests)
    placed = []
    for request in sorted(
        requests, key=lambda r: (-r.size_bytes, r.start, r.end, r.name)
    ):
        if request.size_bytes == 0:
            placed.append((request, None))
            continue
        obstacles = sorted(
            (offset, offset + other.size_bytes)
            for other, offset in placed
            if offset is not None and live_overlap(request, other)
        )
        offset = 0
        for start, end in obstacles:
            if offset + request.size_bytes <= start:
                break
            if offset < end:
                offset = align_up(end, request.alignment)
        placed.append((request, offset))
    return tuple(
        Placement(r.name, offset)
        for r, offset in sorted(placed, key=lambda pair: pair[0].name)
    )


def validate_placements(
    requests: tuple[BufferRequest, ...],
    placements: tuple[Placement, ...],
    capacity: int,
) -> int:
    """Independent exhaustive interval/collision audit, not the allocator loop."""
    validate_requests(requests)
    require(type(capacity) is int and capacity >= 0, "invalid arena capacity")
    require(
        len(placements) == len(requests)
        and len({p.name for p in placements}) == len(placements),
        "placement count/identity mismatch",
    )
    offsets = {p.name: p.offset for p in placements}
    require(
        set(offsets) == {r.name for r in requests},
        "placement names differ from requests",
    )
    for r in requests:
        offset = offsets[r.name]
        if r.size_bytes == 0:
            require(offset is None, f"{r.name}: zero-byte buffers must have no address")
        else:
            require(
                type(offset) is int and offset >= 0 and offset % r.alignment == 0,
                f"{r.name}: negative, missing or misaligned offset",
            )
            require(
                offset + r.size_bytes <= capacity, f"{r.name}: exceeds arena bounds"
            )
    checked = 0
    for i, a in enumerate(requests):
        for b in requests[i + 1 :]:
            if not a.size_bytes or not b.size_bytes or not live_overlap(a, b):
                continue
            checked += 1
            ao, bo = offsets[a.name], offsets[b.name]
            require(
                ao + a.size_bytes <= bo or bo + b.size_bytes <= ao,
                f"live buffer collision: {a.name} and {b.name}",
            )
    return checked


@dataclass(frozen=True)
class MemoryOptions:
    arena_alignment: int = 16
    allow_reshape_views: bool = True
    preserve_inputs: bool = False
    workspace_budget_bytes: int | None = None
    rodata_budget_bytes: int | None = None
    stack_reserve_bytes: int | None = None

    def validate(self) -> None:
        alignment(self.arena_alignment)
        require(
            type(self.allow_reshape_views) is bool
            and type(self.preserve_inputs) is bool,
            "memory policy flags must be booleans",
        )
        for value in (
            self.workspace_budget_bytes,
            self.rodata_budget_bytes,
            self.stack_reserve_bytes,
        ):
            require(
                value is None or type(value) is int and value >= 0,
                "memory budgets/reserves must be nonnegative integers",
            )


@dataclass(frozen=True)
class TensorMemory:
    tensor: int
    name: str
    storage: str
    section: str
    size_bytes: int
    alignment: int
    producer: int | None
    first_use: int | None
    last_consumer: int | None
    start: int
    end: int
    group: str
    offset: int | None = None
    alias_of: int | None = None


@dataclass(frozen=True)
class ParameterMemory:
    node: int
    offset: int | None
    size_bytes: int
    # Defined target layout: sorted fields, contiguous little-endian INT32,
    # arrays in original channel order. No host-struct sizeof estimates.
    fields: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True)
class ScratchMemory:
    node: int
    name: str
    size_bytes: int
    alignment: int
    enabled: bool
    condition: str
    start: int
    end: int
    group: str
    offset: int | None = None


@dataclass(frozen=True)
class AliasDecision:
    node: int
    source: int
    output: int
    enabled: bool
    reason: str


@dataclass(frozen=True)
class MemoryPlan:
    graph_ir_sha256: str
    prepared_ir_sha256: str
    kernel_memory_sha256: str
    options: MemoryOptions
    tensors: tuple[TensorMemory, ...]
    parameters: tuple[ParameterMemory, ...]
    scratch: tuple[ScratchMemory, ...]
    aliases: tuple[AliasDecision, ...]
    requests: tuple[BufferRequest, ...]
    placements: tuple[Placement, ...]
    arena_bytes: int
    arena_alignment: int
    rodata_bytes: int
    rodata_alignment: int
    summary: dict
    schema_version: int = 1
    algorithm: str = "size_descending_aligned_first_fit_v1"

    def to_json(self) -> str:
        return canonical(asdict(self))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    @classmethod
    def from_json(
        cls,
        text: str,
        graph: Graph,
        prepared: PreparedGraph,
        contracts: KernelMemoryPlan,
    ) -> MemoryPlan:
        try:
            data = json.loads(text)
            data["options"] = MemoryOptions(**data["options"])
            for key, record in (
                ("tensors", TensorMemory),
                ("scratch", ScratchMemory),
                ("aliases", AliasDecision),
                ("requests", BufferRequest),
                ("placements", Placement),
            ):
                data[key] = tuple(record(**v) for v in data[key])
            data["parameters"] = tuple(
                ParameterMemory(**{**v, "fields": tuple(tuple(f) for f in v["fields"])})
                for v in data["parameters"]
            )
            plan = cls(**data)
            validate_memory_plan(plan, graph, prepared, contracts)
            return plan
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, ModelError):
                raise
            raise ModelError(f"invalid serialized memory plan: {error}") from error


def _problem(
    graph: Graph,
    prepared: PreparedGraph,
    contracts: KernelMemoryPlan,
    options: MemoryOptions,
    context: CompilationContext,
):
    validate_graph(graph)
    options.validate()
    # Reject fabricated/stale Stage 2 data; this is offline validation only.
    context.check(graph, prepared)
    validate_contracts(graph, contracts)
    n = len(graph.nodes)
    alignments = [TYPE_FORMATS[t.dtype][1] for t in graph.tensors]
    mutates = set()
    for node, contract in zip(graph.nodes, contracts.nodes):
        for operand, memory in zip(node.inputs, contract.inputs):
            if operand.tensor is not None:
                alignments[operand.tensor] = max(
                    alignments[operand.tensor], memory.alignment
                )
                if memory.access == "read_write":
                    mutates.add(operand.tensor)
        for tensor, required in zip(node.outputs, contract.output_alignments):
            alignments[tensor] = max(alignments[tensor], required)
    tensors = []
    rodata = 0
    for t in graph.tensors:
        first, last = (
            (min(t.consumers), max(t.consumers)) if t.consumers else (None, None)
        )
        if t.storage == "constant":
            rodata = align_up(rodata, alignments[t.index])
            record = TensorMemory(
                t.index,
                t.name,
                "constant",
                ".rodata",
                t.byte_length,
                alignments[t.index],
                None,
                first,
                last,
                -1,
                n,
                f"constant:{t.index}",
                rodata,
            )
            rodata += t.byte_length
        else:
            start = -1 if t.index in graph.inputs else t.producer
            end = max(start, last if last is not None else start)
            if (
                t.index in graph.outputs
                or options.preserve_inputs
                and t.index in graph.inputs
            ):
                end = n
            record = TensorMemory(
                t.index,
                t.name,
                "runtime",
                ".bss",
                t.byte_length,
                alignments[t.index],
                t.producer,
                first,
                last,
                start,
                end,
                f"tensor:{t.index}",
            )
        tensors.append(record)
    # Union only proven views. Parent chains make branches/transitive aliases
    # share the maximum alignment and the entire connected lifetime union.
    parents = list(range(len(tensors)))

    def root(index):
        while parents[index] != index:
            index = parents[index]
        return index

    aliases = []
    for node, contract in zip(graph.nodes, contracts.nodes):
        if node.kind != "RESHAPE":
            continue
        source, out = node.input("input"), node.outputs[0]
        a, b = graph.tensors[source], graph.tensors[out]
        members = [
            i for i in range(len(tensors)) if root(i) in (root(source), root(out))
        ]
        if not options.allow_reshape_views or not contract.reshape_view:
            enabled, reason = False, "copy: views disabled by policy or kernel contract"
        elif a.storage != "runtime":
            enabled, reason = (
                False,
                "copy: immutable-source views outside this storage contract",
            )
        elif (a.dtype, a.byte_length, a.quantization) != (
            b.dtype,
            b.byte_length,
            b.quantization,
        ):
            enabled, reason = False, "copy: representation or quantization differs"
        elif mutates.intersection(members):
            enabled, reason = False, "copy: a source/view consumer can write an operand"
        else:
            enabled, reason = (
                True,
                "view: identical flat representation; all group consumers read only",
            )
        if enabled:
            parents[out] = root(source)
            tensors[out] = replace(tensors[out], storage="alias", alias_of=source)
        aliases.append(AliasDecision(node.index, source, out, enabled, reason))
    groups = {}
    for t in tensors:
        if t.section == ".bss":
            groups.setdefault(root(t.tensor), []).append(t)
    requests = []
    for index, members in sorted(groups.items()):
        group = f"tensor:{index}"
        require(
            len({t.size_bytes for t in members}) == 1, "view group byte lengths differ"
        )
        requests.append(
            BufferRequest(
                group,
                members[0].size_bytes,
                max(t.alignment for t in members),
                min(t.start for t in members),
                max(t.end for t in members),
            )
        )
        for t in members:
            tensors[t.tensor] = replace(t, group=group)
    parameters = []
    for node in prepared.nodes:
        fields = []
        size = 0
        for key, value in sorted(
            parameter_values(node, contracts.nodes[node.node]).items()
        ):
            values = value if isinstance(value, list) else [value]
            require(
                all(type(v) is int and -(1 << 31) <= v < (1 << 31) for v in values),
                "parameter layout requires INT32 values",
            )
            if key in (
                "xrequant_descriptors",
                "depthwise_biases",
                "stem_weights",
                "stem_biases",
            ):
                size = align_up(size, 8)
            fields.append((key, size, len(values)))
            size += 4 * len(values)
        parameter_alignment = (
            8 if contracts.nodes[node.node].parameter_format == "xrequant_v1" else 4
        )
        offset = align_up(rodata, parameter_alignment) if size else None
        if size:
            rodata = offset + size
        parameters.append(ParameterMemory(node.node, offset, size, tuple(fields)))
    scratch_records = []
    for contract in contracts.nodes:
        for s in contract.scratch:
            group = f"scratch:{contract.node}:{s.name}"
            scratch_records.append(
                ScratchMemory(
                    contract.node,
                    s.name,
                    s.size_bytes,
                    s.alignment,
                    s.enabled,
                    s.condition,
                    contract.node,
                    contract.node,
                    group,
                )
            )
            if s.enabled:
                requests.append(
                    BufferRequest(
                        group,
                        s.size_bytes,
                        s.alignment,
                        contract.node,
                        contract.node,
                        "scratch",
                    )
                )
    rodata = align_up(
        rodata,
        max(
            [
                4,
                8
                if any(c.parameter_format == "xrequant_v1" for c in contracts.nodes)
                else 4,
                *(t.alignment for t in tensors if t.section == ".rodata"),
            ]
        ),
    )
    return (
        tuple(tensors),
        tuple(parameters),
        tuple(scratch_records),
        tuple(aliases),
        tuple(requests),
        rodata,
    )


def _summary(
    graph, tensors, scratch, requests, placements, arena_bytes, rodata_bytes, options
):
    timeline = []
    offsets = {p.name: p.offset for p in placements}
    for epoch in range(-1, len(graph.nodes) + 1):
        live = [r for r in requests if r.start <= epoch <= r.end and r.size_bytes]
        activation = sum(r.size_bytes for r in live if r.category == "activation")
        temporary = sum(r.size_bytes for r in live if r.category == "scratch")
        timeline.append(
            {
                "epoch": epoch,
                "activation_bytes": activation,
                "scratch_bytes": temporary,
                "live_bytes": activation + temporary,
                "address_extent_bytes": max(
                    (offsets[r.name] + r.size_bytes for r in live), default=0
                ),
                "groups": sorted(r.name for r in live),
                "tensors": [
                    t.tensor
                    for t in tensors
                    if t.section == ".bss" and t.start <= epoch <= t.end
                ],
            }
        )
    warnings = [
        "Workspace excludes stack, platform data, code and linker padding; total target RAM/ELF use is unmeasured."
    ]
    if options.workspace_budget_bytes is None:
        warnings.append(
            "No workspace budget supplied; physical target RAM capacity is unverified."
        )
    if options.stack_reserve_bytes is None:
        warnings.append(
            "Stack peak is pending a Stage 4 build; no stack reserve supplied."
        )
    else:
        warnings.append(
            "Stack reserve is a caller-specified budget, not a measured stack peak."
        )
    peak = max(t["live_bytes"] for t in timeline)
    return {
        "constant_tensor_bytes": sum(
            t.size_bytes for t in tensors if t.section == ".rodata"
        ),
        "parameter_layout_and_padding_bytes": rodata_bytes
        - sum(t.size_bytes for t in tensors if t.section == ".rodata"),
        "rodata_layout_bytes": rodata_bytes,
        "runtime_tensor_bytes_without_reuse": sum(
            t.size_bytes for t in tensors if t.section == ".bss"
        ),
        "peak_live_activation_bytes": max(t["activation_bytes"] for t in timeline),
        "peak_live_scratch_bytes": max(t["scratch_bytes"] for t in timeline),
        "peak_live_workspace_bytes": peak,
        "workspace_capacity_bytes": arena_bytes,
        "workspace_alignment_and_fragmentation_bytes": arena_bytes - peak,
        "scratch_request_count": len(scratch),
        "scratch_enabled_count": sum(s.enabled and s.size_bytes > 0 for s in scratch),
        "stack_peak_bytes": None,
        "workspace_plus_explicit_stack_reserve_bytes": None
        if options.stack_reserve_bytes is None
        else arena_bytes + options.stack_reserve_bytes,
        "total_target_ram_bytes": None,
        "b0_total_arena_used_bytes": 1688176,
        "b0_comparison": "AOT activation/scratch workspace vs TFLM TOTAL arena including persistent interpreter metadata; not equivalent accounting or a measured runtime reduction.",
        "timeline": timeline,
        "warnings": warnings,
        "capabilities": {
            "memory_plan": True,
            "inference_codegen": False,
            "measured_stack": False,
        },
    }


def _budgets(plan: MemoryPlan) -> None:
    for name, size, limit in (
        ("workspace", plan.arena_bytes, plan.options.workspace_budget_bytes),
        ("rodata", plan.rodata_bytes, plan.options.rodata_budget_bytes),
    ):
        require(
            limit is None or size <= limit,
            f"{name} budget exceeded: requires {size} bytes, limit {limit}",
        )


def plan_memory(
    graph: Graph,
    prepared: PreparedGraph | None = None,
    contracts: KernelMemoryPlan | None = None,
    options: MemoryOptions | None = None,
    *,
    context: CompilationContext | None = None,
) -> MemoryPlan:
    options = MemoryOptions() if options is None else options
    context = CompilationContext(graph) if context is None else context
    prepared = context.prepared if prepared is None else prepared
    contracts = reference_memory_contracts(graph) if contracts is None else contracts
    problem = _problem(graph, prepared, contracts, options, context)
    tensors, parameters, scratch, aliases, requests, rodata = problem
    placements = first_fit(requests)
    offsets = {p.name: p.offset for p in placements}
    base_alignment = max(
        [options.arena_alignment, *(r.alignment for r in requests if r.size_bytes)]
    )
    arena_bytes = align_up(
        max(
            (offsets[r.name] + r.size_bytes for r in requests if r.size_bytes),
            default=0,
        ),
        base_alignment,
    )
    tensors = tuple(
        replace(t, offset=offsets[t.group]) if t.section == ".bss" else t
        for t in tensors
    )
    scratch = tuple(
        replace(s, offset=offsets[s.group]) if s.enabled else s for s in scratch
    )
    result = MemoryPlan(
        graph.sha256,
        prepared.sha256,
        contracts.sha256,
        options,
        tensors,
        parameters,
        scratch,
        aliases,
        requests,
        placements,
        arena_bytes,
        base_alignment,
        rodata,
        max(
            [
                4,
                8
                if any(c.parameter_format == "xrequant_v1" for c in contracts.nodes)
                else 4,
                *(t.alignment for t in tensors if t.section == ".rodata"),
            ]
        ),
        _summary(
            graph, tensors, scratch, requests, placements, arena_bytes, rodata, options
        ),
    )
    _validate_memory_plan(result, graph, prepared, contracts, problem)
    return result


def validate_memory_plan(
    plan: MemoryPlan,
    graph: Graph,
    prepared: PreparedGraph,
    contracts: KernelMemoryPlan,
    *,
    context: CompilationContext | None = None,
) -> dict:
    context = CompilationContext(graph) if context is None else context
    problem = _problem(graph, prepared, contracts, plan.options, context)
    return _validate_memory_plan(plan, graph, prepared, contracts, problem)


def _validate_memory_plan(plan, graph, prepared, contracts, problem):
    tensors, parameters, scratch, aliases, requests, rodata = problem
    require(
        plan.schema_version == 1
        and plan.algorithm == "size_descending_aligned_first_fit_v1",
        "unsupported memory plan schema/algorithm",
    )
    require(
        (plan.graph_ir_sha256, plan.prepared_ir_sha256, plan.kernel_memory_sha256)
        == (graph.sha256, prepared.sha256, contracts.sha256),
        "memory plan provenance mismatch",
    )
    require(
        canonical([asdict(r) for r in plan.requests])
        == canonical([asdict(r) for r in requests]),
        "memory requests/lifetimes differ from graph/contracts",
    )
    pairs = validate_placements(requests, plan.placements, plan.arena_bytes)
    offsets = {p.name: p.offset for p in plan.placements}
    base = max(
        [plan.options.arena_alignment, *(r.alignment for r in requests if r.size_bytes)]
    )
    extent = max(
        (offsets[r.name] + r.size_bytes for r in requests if r.size_bytes), default=0
    )
    require(
        type(plan.arena_alignment) is int
        and plan.arena_alignment == base
        and plan.arena_bytes == align_up(extent, base),
        "arena extent/base alignment mismatch",
    )
    require(
        plan.rodata_bytes == rodata
        and plan.rodata_alignment
        == max(
            [
                4,
                8
                if any(c.parameter_format == "xrequant_v1" for c in contracts.nodes)
                else 4,
                *(t.alignment for t in tensors if t.section == ".rodata"),
            ]
        ),
        "rodata extent/base alignment mismatch",
    )
    expected_tensors = tuple(
        replace(t, offset=offsets[t.group]) if t.section == ".bss" else t
        for t in tensors
    )
    expected_scratch = tuple(
        replace(s, offset=offsets[s.group]) if s.enabled else s for s in scratch
    )
    for name, actual, expected in (
        ("tensors", plan.tensors, expected_tensors),
        ("parameters", plan.parameters, parameters),
        ("scratch", plan.scratch, expected_scratch),
        ("aliases", plan.aliases, aliases),
    ):
        require(
            canonical([asdict(r) for r in actual])
            == canonical([asdict(r) for r in expected]),
            f"{name} storage/alias metadata differs from proof",
        )
    # Audit the read-only address intervals independently too. These offsets
    # are sequential rather than lifetime-reused, but still must obey type
    # alignment, bounds and nonoverlap across constants and prepared params.
    readonly = [
        (t.offset, t.size_bytes, t.alignment)
        for t in plan.tensors
        if t.section == ".rodata"
    ]
    readonly.extend(
        (p.offset, p.size_bytes, 4) for p in plan.parameters if p.size_bytes
    )
    previous_end = 0
    for offset, size, required_alignment in sorted(readonly):
        require(
            type(offset) is int
            and offset % required_alignment == 0
            and previous_end <= offset
            and offset + size <= plan.rodata_bytes,
            "read-only alignment, bounds or collision failure",
        )
        previous_end = offset + size
    _budgets(plan)
    expected_summary = _summary(
        graph,
        expected_tensors,
        expected_scratch,
        requests,
        plan.placements,
        plan.arena_bytes,
        rodata,
        plan.options,
    )
    require(
        canonical(plan.summary) == canonical(expected_summary),
        "memory plan summary/timeline differs from placements",
    )
    return {
        "status": "PASS",
        "live_buffer_pairs_checked": pairs,
        "buffers_checked": len(requests),
        "readonly_buffers_checked": len(readonly),
        "proven_views": sum(a.enabled for a in aliases),
        "checks": [
            "inclusive_lifetimes",
            "alignment",
            "arena_bounds",
            "all_live_pairs",
            "alias_proof",
            "rodata_layout",
            "budgets",
        ],
    }
