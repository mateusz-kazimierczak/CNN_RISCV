"""Compiler-owned logical origins and observable execution units (no target code)."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass

from .ir import Graph, ModelError
from .kernel_plan import pointwise_block_size, pointwise_pixels, depthwise_filter_size


@dataclass(frozen=True)
class ExecutionUnit:
    id: str
    order: int
    nodes: tuple[int, ...]
    symbol: str
    implementation: str
    arithmetic_backend: str
    inputs: tuple[int, ...]
    outputs: tuple[int, ...]
    source: dict
    memory: dict
    work: dict
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionPlan:
    graph_ir_sha256: str
    prepared_ir_sha256: str
    memory_plan_sha256: str
    units: tuple[ExecutionUnit, ...]
    origins: tuple[dict, ...]
    configuration: str = "A0"
    inference_symbol: str = "a0_invoke"
    schema_version: int = 2
    kernel_plan_sha256: str = ""

    def to_json(self):
        return (
            json.dumps(asdict(self), sort_keys=True, indent=2, allow_nan=False) + "\n"
        )

    @classmethod
    def from_json(cls, text):
        data = json.loads(text)
        data["units"] = tuple(
            ExecutionUnit(
                **{
                    **u,
                    **{k: tuple(u[k]) for k in ("nodes", "inputs", "outputs", "notes")},
                }
            )
            for u in data["units"]
        )
        data["origins"] = tuple(data["origins"])
        return cls(**data)


def validate_execution_plan(plan: ExecutionPlan, graph: Graph):
    def require(ok, message):
        if not ok:
            raise ModelError("execution plan: " + message)

    require(
        plan.schema_version == 2 and plan.graph_ir_sha256 == graph.sha256,
        "schema/graph mismatch",
    )
    require(
        bool(plan.configuration) and bool(plan.inference_symbol),
        "missing configuration/root",
    )
    ids = [u.id for u in plan.units]
    require(len(set(ids)) == len(ids), "duplicate unit ID")
    require(
        [u.order for u in plan.units] == list(range(len(ids))), "nonsequential schedule"
    )
    require(
        [o["node"] for o in plan.origins] == list(range(len(graph.nodes))),
        "logical origin coverage",
    )
    for unit in plan.units:
        require(
            bool(unit.id)
            and bool(unit.symbol)
            and bool(unit.implementation)
            and bool(unit.arithmetic_backend),
            "incomplete unit identity",
        )
        require(
            bool(unit.nodes)
            and len(set(unit.nodes)) == len(unit.nodes)
            and all(type(n) is int and 0 <= n < len(graph.nodes) for n in unit.nodes),
            "invalid original nodes",
        )
        require(
            all(
                type(t) is int and 0 <= t < len(graph.tensors)
                for t in (*unit.inputs, *unit.outputs)
            ),
            "invalid operand",
        )
        require(
            unit.source.get("line", 0) > 0
            and unit.source.get("end_line", 0) >= unit.source["line"]
            and bool(unit.source.get("file")),
            "invalid source region",
        )
        require(
            unit.work.get("evidence") in ("derived", "unavailable"),
            "work is not a retirement measurement",
        )
        for key in ("logical_macs", "executed_products"):
            value = unit.work.get(key)
            require(
                value is None or (type(value) is int and value >= 0),
                "invalid work count",
            )
    for origin in plan.origins:
        expected = [u.id for u in plan.units if origin["node"] in u.nodes]
        require(origin["unit_ids"] == expected, "origin/unit relationships disagree")
        require(
            origin["disposition"] in ("executed", "eliminated"),
            "unknown origin disposition",
        )
        require(
            bool(expected) == (origin["disposition"] == "executed"),
            "eliminated origin has measured work",
        )
        if not expected:
            require(
                bool(origin.get("reason")), "eliminated origin needs an explanation"
            )


def validate_kernel_link(plan: ExecutionPlan, saved: dict) -> None:
    """Join saved evidence without reselecting kernels using the working tree."""
    identity = hashlib.sha256(
        (json.dumps(saved, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    ).hexdigest()
    if (
        saved.get("schema_version") != 1
        or identity != plan.kernel_plan_sha256
        or saved["graph_ir_sha256"] != plan.graph_ir_sha256
        or saved["prepared_ir_sha256"] != plan.prepared_ir_sha256
        or saved["configuration"] != plan.configuration
        or len(saved["nodes"]) != len(plan.units)
    ):
        raise ModelError("execution/kernel plan linkage mismatch")
    for selection, unit in zip(saved["nodes"], plan.units):
        if (
            unit.nodes != (selection["node"],)
            or unit.implementation != selection["implementation"]
            or unit.arithmetic_backend != selection["arithmetic_backend"]
            or json.loads(json.dumps(unit.memory.get("kernel_selection"))) != selection
        ):
            raise ModelError("execution unit differs from selected kernel")


def reference_work(graph, node):
    logical = executed = 0
    policy = "no_dot_products"
    if node.kind in ("CONV_2D", "DEPTHWISE_CONV_2D"):
        a = graph.tensors[node.source_inputs[0]].shape
        w = graph.tensors[node.source_inputs[1]].shape
        out = graph.tensors[node.outputs[0]].shape
        kh, kw = w[1:3]
        opts = node.options
        channels = out[3] * (w[3] if node.kind == "CONV_2D" else 1)
        logical = out[0] * out[1] * out[2] * channels * kh * kw

        def taps(size, count, kernel, stride, dilation):
            pad = (
                max(0, (count - 1) * stride + (kernel - 1) * dilation + 1 - size) // 2
                if opts.padding == "SAME"
                else 0
            )
            return sum(
                0 <= o * stride - pad + k * dilation < size
                for o in range(count)
                for k in range(kernel)
            )

        executed = (
            out[0]
            * channels
            * taps(a[1], out[1], kh, opts.stride_h, opts.dilation_h)
            * taps(a[2], out[2], kw, opts.stride_w, opts.dilation_w)
        )
        policy = "pinned_reference_skips_padding"
    elif node.kind == "FULLY_CONNECTED":
        logical = executed = (
            math.prod(graph.tensors[node.outputs[0]].shape)
            * graph.tensors[node.source_inputs[1]].shape[-1]
        )
        policy = "dense_reference_dot_product"
    return {
        "logical_macs": logical,
        "executed_products": executed,
        "evidence": "derived",
        "policy": policy,
    }


def make_execution_plan(model, mapping):
    units = []
    for node, source, selection in zip(
        model.graph.nodes, mapping["nodes"], model.kernels.nodes
    ):
        contract = selection.memory
        work = reference_work(model.graph, node)
        if pointwise_block_size(selection):
            work["policy"] = (
                "dense_pointwise_scalar_dot8_spatial2"
                if pointwise_pixels(selection) == 2
                else "dense_pointwise_scalar_dot8"
            )
        if depthwise_filter_size(selection):
            work["policy"] = "depthwise_static_valid_taps"
        if selection.implementation == "rv64imc/stem_rgb_xqmac8/int8":
            work["executed_products"] = math.prod(selection.geometry.output_shape) * 32
            work["policy"] = "stem_patch27_zero_padded32_including_invalid_taps"
        if selection.implementation == "project/stem_rgb3x3/int8":
            work["policy"] = "project_stem_skips_padding"
        if selection.implementation == "project/fully_connected/int8":
            work["policy"] = "project_fc_dense"
        units.append(
            ExecutionUnit(
                id=f"node:{node.index}",
                order=node.index,
                nodes=(node.index,),
                symbol=source["symbol"],
                implementation=selection.implementation,
                arithmetic_backend=selection.arithmetic_backend,
                inputs=tuple(t for t in node.source_inputs if t >= 0),
                outputs=node.outputs,
                source={
                    "file": source["source"],
                    "line": source["line"],
                    "end_line": source["end_line"],
                },
                memory={
                    "kernel_selection": json.loads(model.kernels.to_json())["nodes"][
                        node.index
                    ],
                    "tensors": [
                        asdict(model.memory.tensors[t])
                        for t in (*node.source_inputs, *node.outputs)
                        if t >= 0
                    ],
                    "parameters": {
                        **asdict(model.memory.parameters[node.index]),
                        "fields": [
                            list(f) for f in model.memory.parameters[node.index].fields
                        ],
                    },
                    "scratch": [
                        asdict(s) for s in model.memory.scratch if s.node == node.index
                    ],
                },
                work=work,
                notes=(
                    ("Includes extra exp/sum Softmax domain preflight.",)
                    if node.kind == "SOFTMAX"
                    else (
                        (
                            "Read-only Reshape view; existing wrapper call/return is measured.",
                        )
                        if contract.reshape_view
                        else ()
                    )
                ),
            )
        )
    plan = ExecutionPlan(
        model.context.graph_sha256,
        model.prepared.sha256,
        model.memory.sha256,
        tuple(units),
        tuple(
            {
                "node": n.index,
                "unit_ids": [f"node:{n.index}"],
                "disposition": "executed",
            }
            for n in model.graph.nodes
        ),
        configuration=model.kernels.configuration,
        kernel_plan_sha256=model.kernels.sha256,
    )
    validate_execution_plan(plan, model.graph)
    return plan
