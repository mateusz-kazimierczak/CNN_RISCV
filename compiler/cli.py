"""Import, validate and inspect the fixed model; inference generation is gated."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .ir import ModelError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("import", "validate", "inspect", "generate", "plan-memory"):
        command = commands.add_parser(
            name,
            help=f"{name} the frozen TFLite model",
        )
        command.add_argument("model", type=Path, help="input TFLite file")
        if name in ("import", "generate"):
            command.add_argument(
                "--output-dir",
                type=Path,
                default=None if name == "generate" else Path("build/compiler/import"),
            )
            if name == "generate":
                command.add_argument(
                    "--runtime",
                    choices=(
                        "reference",
                        "project-numerics",
                        "project-kernels",
                        "standalone",
                    ),
                    default=None,
                )
                command.add_argument("--config", choices=("A0", "B1"), default="A0")
                command.add_argument("--prepared-ir", type=Path)
                command.add_argument("--memory-plan", type=Path)
                command.add_argument("--kernel-plan", type=Path)
                command.add_argument(
                    "--pointwise-block",
                    type=int,
                    choices=(1, 2, 4),
                    default=None,
                    help="B1: output channels per scalar dot8 block (default 1)",
                )
                command.add_argument(
                    "--depthwise-kernels",
                    type=int,
                    nargs="+",
                    choices=(3, 5),
                    default=None,
                    help="B1: specialize selected depthwise filter sizes",
                )
                command.add_argument(
                    "--stem-unroll",
                    action="store_const",
                    const=True,
                    default=None,
                    help="B1: enable function-local GCC loop unrolling for the RGB stem",
                )
        elif name == "plan-memory":
            command.add_argument(
                "--output-dir", type=Path, default=Path("build/compiler/memory")
            )
            command.add_argument("--prepared-ir", type=Path)
            command.add_argument("--workspace-budget-bytes", type=int)
            command.add_argument("--rodata-budget-bytes", type=int)
            command.add_argument("--stack-reserve-bytes", type=int)
            command.add_argument("--arena-alignment", type=int, default=16)
            command.add_argument("--copy-reshape", action="store_true")
            command.add_argument("--preserve-inputs", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "generate" and args.depthwise_kernels is not None:
        args.depthwise_kernels.sort()
    if args.command == "generate" and args.output_dir is None:
        args.output_dir = Path("build/compiler") / args.config
    try:
        from .export import export_graph, node_table
        from .frontend import import_model
        from .validation import validate_project_model

        graph = import_model(args.model)
        audit = (
            Path(__file__).resolve().parents[1]
            / "models/efficientnet-lite0-int8.audit.json"
        )
        validate_project_model(graph, json.loads(audit.read_text()))
        if args.command == "generate":
            from .project_runtime import runtime_mode
            from .emit_cpp import emit_cpp
            from .kernel_plan import (
                KernelPlan,
                select_kernels,
                uses_stem_unroll,
                selected_depthwise_kernels,
            )
            from .lowering import lower_graph
            from .memory_plan import MemoryPlan
            from .quantization import PreparedGraph, prepare_graph

            prepared = (
                prepare_graph(graph)
                if args.prepared_ir is None
                else PreparedGraph.from_json(args.prepared_ir.read_text(), graph)
            )
            kernels = (
                select_kernels(
                    graph,
                    prepared,
                    args.config,
                    runtime=args.runtime or "reference",
                    stem_unroll=bool(args.stem_unroll),
                    depthwise_kernels=tuple(args.depthwise_kernels or ()),
                    pointwise_block=1
                    if args.pointwise_block is None
                    else args.pointwise_block,
                )
                if args.kernel_plan is None
                else KernelPlan.from_json(args.kernel_plan.read_text(), graph, prepared)
            )
            if args.runtime is not None and args.runtime != runtime_mode(kernels):
                raise ModelError("supplied kernel plan differs from --runtime")
            if kernels.configuration != args.config:
                raise ModelError(
                    "supplied kernel plan configuration differs from --config"
                )
            if args.stem_unroll is not None and args.stem_unroll != uses_stem_unroll(
                kernels
            ):
                raise ModelError("supplied kernel plan differs from --stem-unroll")
            if args.depthwise_kernels is not None and tuple(
                args.depthwise_kernels
            ) != selected_depthwise_kernels(kernels):
                raise ModelError(
                    "supplied kernel plan differs from --depthwise-kernels"
                )
            if args.pointwise_block is not None and kernels != select_kernels(
                graph,
                prepared,
                args.config,
                runtime=runtime_mode(kernels),
                stem_unroll=uses_stem_unroll(kernels),
                pointwise_block=args.pointwise_block,
                depthwise_kernels=selected_depthwise_kernels(kernels),
            ):
                raise ModelError("supplied kernel plan differs from --pointwise-block")
            memory = (
                None
                if args.memory_plan is None
                else MemoryPlan.from_json(
                    args.memory_plan.read_text(),
                    graph,
                    prepared,
                    kernels.memory_contracts,
                )
            )
            manifest = emit_cpp(
                lower_graph(graph, prepared, memory, kernels=kernels), args.output_dir
            )
            print(
                f"Generated {kernels.configuration} model ({len(graph.nodes)} nodes): {args.output_dir.resolve()}"
            )
            print(f"model_cc_sha256={manifest['artifacts']['model.cc']}")
        elif args.command == "plan-memory":
            from .kernel_plan import reference_memory_contracts
            from .memory_export import export_memory
            from .memory_plan import MemoryOptions, plan_memory
            from .quantization import PreparedGraph, prepare_graph

            prepared = (
                prepare_graph(graph)
                if args.prepared_ir is None
                else PreparedGraph.from_json(args.prepared_ir.read_text(), graph)
            )
            contracts = reference_memory_contracts(graph)
            options = MemoryOptions(
                arena_alignment=args.arena_alignment,
                allow_reshape_views=not args.copy_reshape,
                preserve_inputs=args.preserve_inputs,
                workspace_budget_bytes=args.workspace_budget_bytes,
                rodata_budget_bytes=args.rodata_budget_bytes,
                stack_reserve_bytes=args.stack_reserve_bytes,
            )
            plan = plan_memory(graph, prepared, contracts, options)
            export_memory(graph, prepared, contracts, plan, args.output_dir)
            print(
                f"Static memory plan: PASS ({plan.arena_bytes:,} workspace bytes; {plan.rodata_bytes:,} read-only layout bytes)"
            )
            print(f"memory_plan_sha256={plan.sha256}")
            for warning in plan.summary["warnings"]:
                print(f"Note: {warning}")
        elif args.command == "inspect":
            print(node_table(graph), end="")
        elif args.command == "import":
            manifest = export_graph(graph, args.output_dir)
            print(
                f"Imported {len(graph.nodes)} nodes / {len(graph.tensors)} tensors to {args.output_dir.resolve()}"
            )
            print(f"graph_ir_sha256={manifest['artifacts']['graph_ir.json']}")
        else:
            print(
                f"Model validation: PASS ({len(graph.nodes)} nodes, {len(graph.tensors)} tensors, 1 subgraph)"
            )
            print(f"model_sha256={graph.model_sha256}")
        return 0
    except (
        OSError,
        ModelError,
        KeyError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"{args.command} failed: {error}", file=sys.stderr)
        return 1
