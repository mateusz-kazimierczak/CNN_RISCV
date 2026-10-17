"""Stage 3 artifacts and provenance, kept separate from Stage 1/2 exports."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .frontend import DEPENDENCIES
from .ir import Graph
from .kernel_plan import KernelMemoryPlan, require
from .memory_plan import MemoryPlan, canonical, validate_memory_plan
from .quantization import PreparedGraph

ROOT = Path(__file__).resolve().parents[1]


def export_memory(
    graph: Graph,
    prepared: PreparedGraph,
    contracts: KernelMemoryPlan,
    plan: MemoryPlan,
    output: Path,
) -> dict:
    audit = validate_memory_plan(plan, graph, prepared, contracts)
    chart = {
        "schema_version": 1,
        "epochs": {
            "input_setup": -1,
            "first_node": 0,
            "last_node": len(graph.nodes) - 1,
            "output_handoff": len(graph.nodes),
            "intervals": "inclusive",
        },
        "tensors": [asdict(t) for t in plan.tensors],
        "scratch": [asdict(s) for s in plan.scratch],
        "physical_groups": [
            {
                **asdict(r),
                "offset": next(p.offset for p in plan.placements if p.name == r.name),
            }
            for r in plan.requests
        ],
        "timeline": plan.summary["timeline"],
    }
    report = (
        f"""# Static memory plan (Stage 3)

Activation/scratch workspace: **{plan.arena_bytes:,} bytes**, base alignment
{plan.arena_alignment}. Peak live activation bytes:
{plan.summary["peak_live_activation_bytes"]:,}; scratch bytes:
{plan.summary["peak_live_scratch_bytes"]:,}. Proven Reshape views: {audit["proven_views"]}.

Constant tensors: {plan.summary["constant_tensor_bytes"]:,} bytes. The defined
INT32 prepared parameter payload is {sum(p.size_bytes for p in plan.parameters):,}
bytes. Read-only layout including alignment: {plan.rodata_bytes:,} bytes,
base alignment {plan.rodata_alignment}. This excludes future generated shape/option
tables, code, and linker padding; it is not a final ELF size.

Collision/alignment/bounds checks: **{audit["status"]}**,
{audit["live_buffer_pairs_checked"]} overlapping-lifetime physical buffer pairs
checked independently of placement. Tensor lifetimes and physical storage-group
lifetimes are exported separately; aliases extend the group's last use.

The pinned B0 uses **1,688,176 bytes of total TFLM arena**, including persistent
interpreter metadata. Comparing that total with activation/scratch workspace
uses different accounting. No runtime memory reduction or performance claim is
made before generated inference exists.

Input setup is epoch -1; each node is one inclusive epoch; output handoff is epoch
{len(graph.nodes)}. By default input storage can be reused after its last read.
Input preservation through handoff is enabled: {plan.options.preserve_inputs}.
Output storage remains live through handoff. Caller output is valid until the
next invocation or workspace reuse; persistent cross-invocation storage is not
part of this plan.

"""
        + "\n".join(f"- {warning}" for warning in plan.summary["warnings"])
        + "\n"
    )
    artifacts = {
        "memory_plan.json": plan.to_json(),
        "kernel_memory_contracts.json": contracts.to_json(),
        "memory_lifetimes.json": canonical(chart),
        "collision_check.json": canonical(audit),
        "memory_report.md": report,
    }

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], check=True, text=True, capture_output=True
        ).stdout.strip()

    sources = (
        "compiler/ir.py",
        "compiler/frontend.py",
        "compiler/validation.py",
        "compiler/quantization.py",
        "compiler/kernel_plan.py",
        "compiler/memory_plan.py",
        "compiler/memory_export.py",
        "compiler/cli.py",
        "tools/compiler/requirements.txt",
        "models/efficientnet-lite0-int8.audit.json",
    )
    upstream = ROOT / ".deps/tflite-micro"
    reference_head = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    reference_diff = subprocess.run(
        ["git", "-C", str(upstream), "diff", "HEAD", "--"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    require(
        reference_head == graph.reference_revision and not reference_diff,
        "memory contract source evidence requires the unmodified pinned TFLM revision",
    )
    paths = []
    for name in (
        "conv",
        "depthwise_conv",
        "fully_connected",
        "add",
        "pooling",
        "quantize",
        "reshape",
        "softmax",
    ):
        paths.extend(
            [
                f"tensorflow/lite/micro/kernels/{name}.cc",
                f"tensorflow/lite/micro/kernels/{name}_common.cc",
            ]
        )
    manifest = {
        "schema_version": 1,
        "stage": 3,
        "generator_version": __version__,
        "repository_revision": git("rev-parse", "HEAD"),
        "repository_dirty_status": git("status", "--porcelain"),
        "reference_revision": graph.reference_revision,
        "model_sha256": graph.model_sha256,
        "graph_ir_sha256": graph.sha256,
        "prepared_ir_sha256": prepared.sha256,
        "kernel_memory_sha256": contracts.sha256,
        "memory_plan_sha256": plan.sha256,
        "dependencies": dict(DEPENDENCIES),
        "options": asdict(plan.options),
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sources
        },
        "reference_kernel_source_sha256": {
            name: hashlib.sha256((upstream / name).read_bytes()).hexdigest()
            for name in paths
        },
        "passes": [
            "static_graph_validation",
            "prepared_parameter_validation",
            "kernel_memory_contracts",
            "tensor_lifetimes",
            "readonly_reshape_alias_proof",
            "aligned_first_fit",
            "independent_collision_audit",
            "workspace_rodata_budgets",
        ],
        "capabilities": {
            "memory_plan": True,
            "inference_codegen": False,
            "measured_stack": False,
        },
        "collision_check": audit,
        "artifacts": {
            name: hashlib.sha256(text.encode()).hexdigest()
            for name, text in artifacts.items()
        },
        "elf_sha256": None,
    }
    # Every proof and budget check finishes before artifacts are written.
    output.mkdir(parents=True, exist_ok=True)
    for name, text in artifacts.items():
        (output / name).write_text(text)
    (output / "manifest.json").write_text(canonical(manifest))
    return manifest
