"""Import, validate and inspect the fixed model; inference generation is gated."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ir import ModelError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("import", "validate", "inspect", "generate"):
        command = commands.add_parser(
            name,
            help="not implemented until Stage 4"
            if name == "generate"
            else f"{name} the frozen TFLite model",
        )
        command.add_argument("model", type=Path, help="input TFLite file")
        if name == "import":
            command.add_argument(
                "--output-dir", type=Path, default=Path("build/compiler/import")
            )
    args = parser.parse_args(argv)
    if args.command == "generate":
        print(
            "generate: not implemented (requires Stage 4); Stage 1 imports graph metadata only.",
            file=sys.stderr,
        )
        return 2
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
        if args.command == "inspect":
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
    except (OSError, ModelError, KeyError, json.JSONDecodeError) as error:
        print(f"{args.command} failed: {error}", file=sys.stderr)
        return 1
