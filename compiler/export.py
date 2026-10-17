"""Deterministic graph artifacts and explicit Stage 1 provenance/capabilities."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from . import __version__
from .frontend import DEPENDENCIES
from .ir import Graph
from .validation import validate_graph

ROOT = Path(__file__).resolve().parents[1]


def node_table(graph: Graph) -> str:
    lines = [
        "# Validated static TFLite graph",
        "",
        f"Model SHA-256: `{graph.model_sha256}`. Original subgraph: {graph.subgraph}.",
        "Prepared integer parameters, memory planning and inference generation are not implemented.",
        "",
        "| Node | Operator | Version | Named inputs | Outputs | Output shapes | Padding T/B/L/R |",
        "|---:|---|---:|---|---|---|---|",
    ]
    for node in graph.nodes:
        inputs = ", ".join(
            f"{operand.name}={'absent' if operand.tensor is None else 't' + str(operand.tensor)}"
            for operand in node.inputs
        )
        outputs = ", ".join(f"t{index}" for index in node.outputs)
        shapes = ", ".join(
            str(list(graph.tensors[index].shape)) for index in node.outputs
        )
        padding = (
            "/".join(
                str(getattr(node.padding, side))
                for side in ("top", "bottom", "left", "right")
            )
            if node.padding
            else "—"
        )
        lines.append(
            f"| {node.index} | {node.kind} | {node.version} | {inputs} | {outputs} | {shapes} | {padding} |"
        )
    return "\n".join(lines) + "\n"


def dot_graph(graph: Graph) -> str:
    lines = ["digraph static_model {", '  rankdir="LR";']
    for tensor in graph.tensors:
        label = f"t{tensor.index}\n{tensor.dtype} {list(tensor.shape)}"
        style = ",style=dashed" if tensor.storage == "constant" else ""
        lines.append(
            f"  t{tensor.index} [shape=ellipse,label={json.dumps(label)},tooltip={json.dumps(tensor.name)}{style}];"
        )
    for node in graph.nodes:
        lines.append(
            f"  n{node.index} [shape=box,label={json.dumps(f'n{node.index}: {node.kind} v{node.version}')}];"
        )
        for operand in node.inputs:
            if operand.tensor is not None:
                lines.append(
                    f"  t{operand.tensor} -> n{node.index} [label={json.dumps(operand.name)}];"
                )
        for slot, output in enumerate(node.outputs):
            lines.append(f'  n{node.index} -> t{output} [label="output{slot}"];')
    return "\n".join([*lines, "}"]) + "\n"


def export_graph(graph: Graph, output: Path) -> dict:
    validate_graph(graph)
    artifacts = {
        "graph_ir.json": graph.to_json(),
        "nodes.md": node_table(graph),
        "graph.dot": dot_graph(graph),
    }

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], check=True, text=True, capture_output=True
        ).stdout.strip()

    sources = (
        "compiler/__init__.py",
        "compiler/cli.py",
        "compiler/frontend.py",
        "compiler/ir.py",
        "compiler/validation.py",
        "compiler/export.py",
        "tools/inspect_tflite.py",
        "tools/compiler/requirements.txt",
        "models/efficientnet-lite0-int8.audit.json",
    )
    manifest = {
        "schema_version": 1,
        "stage": 1,
        "generator_version": __version__,
        "repository_revision": git("rev-parse", "HEAD"),
        "repository_dirty_status": git("status", "--porcelain"),
        "model_sha256": graph.model_sha256,
        "model_size_bytes": graph.model_size_bytes,
        "reference_tflm_revision": graph.reference_revision,
        "dependencies": dict(DEPENDENCIES),
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sources
        },
        "passes": [
            "flatbuffer_import",
            "supported_options_validation",
            "static_shape_inference",
            "producer_consumer_linking",
        ],
        "capabilities": dict(Graph.CAPABILITIES),
        "subgraph_count": 1,
        "operator_count": len(graph.nodes),
        "tensor_count": len(graph.tensors),
        "operator_counts": dict(
            sorted(Counter(node.kind for node in graph.nodes).items())
        ),
        "constant_buffer_bytes": sum(len(buffer.data) for buffer in graph.buffers),
        "runtime_tensor_bytes_without_reuse": sum(
            tensor.byte_length
            for tensor in graph.tensors
            if tensor.storage == "runtime"
        ),
        "arithmetic_backend": None,
        "kernel_plan_sha256": None,
        "memory_plan_sha256": None,
        "elf_sha256": None,
        "artifacts": {
            name: hashlib.sha256(text.encode()).hexdigest()
            for name, text in artifacts.items()
        },
    }
    # No output is created until graph/options/shape validation has succeeded.
    output.mkdir(parents=True, exist_ok=True)
    for name, text in artifacts.items():
        (output / name).write_text(text, encoding="utf-8")
    (output / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
