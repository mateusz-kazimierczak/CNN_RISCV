"""Stage 3 interval, alias, scratch, budget, corruption and real graph gates."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import random
import struct
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fixtures.tflite_builder import O, T, build_model
from test_frontend import conv_fixture

from compiler.cli import main
from compiler.frontend import import_bytes, import_model
from compiler.ir import ModelError
from compiler.kernel_plan import ScratchRequirement, reference_memory_contracts
from compiler.memory_export import export_memory
from compiler.memory_plan import (
    BufferRequest,
    MemoryOptions,
    MemoryPlan,
    Placement,
    first_fit,
    plan_memory,
    validate_memory_plan,
    validate_placements,
)
from compiler.quantization import prepare_graph


def residual_graph():
    tensors = tuple(T((1, 8)) for _ in range(5))
    return import_bytes(
        build_model(
            tensors,
            (O("ADD", (0, 1), (2,)), O("ADD", (2, 1), (3,)), O("ADD", (3, 2), (4,))),
            inputs=(0, 1),
        )
    )


def reshape_chain():
    tensors = (T((1, 1, 1, 8)), T((1, 8)), T((1, 1, 1, 8)), T((1, 8)))
    return import_bytes(
        build_model(
            tensors,
            tuple(
                O(
                    "RESHAPE",
                    (i,),
                    (i + 1,),
                    options={"new_shape": tensors[i + 1].shape},
                )
                for i in range(3)
            ),
        )
    )


def override(contracts, index, **values):
    return replace(
        contracts,
        nodes=tuple(
            replace(n, **values) if i == index else n
            for i, n in enumerate(contracts.nodes)
        ),
    )


class IntervalAllocatorTests(unittest.TestCase):
    def test_inputs_outputs_overlap_on_the_same_node(self):
        requests = (
            BufferRequest("input", 16, 8, -1, 0),
            BufferRequest("output", 16, 8, 0, 1),
        )
        offsets = {p.name: p.offset for p in first_fit(requests)}
        self.assertNotEqual(offsets["input"], offsets["output"])
        self.assertEqual(validate_placements(requests, first_fit(requests), 32), 1)

    def test_dead_buffers_reused_only_after_last_use(self):
        requests = (
            BufferRequest("skip", 100, 16, 0, 4),
            BufferRequest("middle", 100, 16, 1, 2),
            BufferRequest("later", 100, 16, 3, 3),
            BufferRequest("after", 100, 16, 5, 6),
        )
        p = {p.name: p.offset for p in first_fit(requests)}
        self.assertEqual(p["middle"], p["later"])
        self.assertNotEqual(p["skip"], p["later"])
        self.assertEqual(p["skip"], p["after"])

    def test_alignment_gaps_and_lowest_fit(self):
        requests = (
            BufferRequest("a", 9, 1, 0, 0),
            BufferRequest("b", 7, 16, 0, 0),
            BufferRequest("c", 6, 1, 0, 0),
        )
        self.assertEqual(
            {p.name: p.offset for p in first_fit(requests)}, {"a": 0, "b": 16, "c": 9}
        )
        validate_placements(requests, first_fit(requests), 23)

    def test_zero_byte_requests_have_no_address_or_capacity(self):
        requests = (
            BufferRequest("empty", 0, 4096, -1, 100),
            BufferRequest("real", 1, 1, 0, 0),
        )
        p = first_fit(requests)
        self.assertEqual({p.name: p.offset for p in p}, {"empty": None, "real": 0})
        self.assertEqual(validate_placements(requests, p, 1), 0)
        self.assertEqual(first_fit(()), ())
        self.assertEqual(validate_placements((), (), 0), 0)

    def test_large_1_2mb_buffers_without_granularity_or_truncation(self):
        requests = (
            BufferRequest("large", 1204224, 16, 1, 2),
            BufferRequest("next", 1204224, 64, 3, 4),
            BufferRequest("simultaneous", 301056, 16, 2, 3),
        )
        p = first_fit(requests)
        offsets = {p.name: p.offset for p in p}
        self.assertEqual(offsets["large"], offsets["next"])
        validate_placements(requests, p, 1505280)

    def test_invalid_requests_and_placements_rejected(self):
        request = BufferRequest("a", 16, 8, 0, 1)
        for variant in (
            replace(request, size_bytes=-1),
            replace(request, size_bytes=True),
            replace(request, alignment=3),
            replace(request, alignment=0),
            replace(request, start=2),
            replace(request, start=-2),
            replace(request, end=True),
        ):
            with self.subTest(request=variant), self.assertRaises(ModelError):
                first_fit((variant,))
        with self.assertRaises(ModelError):
            first_fit((request, request))
        for p in (
            (),
            (Placement("other", 0),),
            (Placement("a", None),),
            (Placement("a", -8),),
            (Placement("a", 1),),
            (Placement("a", True),),
            (Placement("a", 8),),
        ):
            with self.subTest(placement=p), self.assertRaises(ModelError):
                validate_placements((request,), p, 16)

    def test_independent_checker_detects_forged_live_collision(self):
        requests = (BufferRequest("a", 8, 1, 0, 4), BufferRequest("b", 8, 1, 4, 5))
        with self.assertRaisesRegex(ModelError, "live buffer collision"):
            validate_placements(requests, (Placement("a", 0), Placement("b", 0)), 8)

    def test_randomized_intervals_independent_epoch_bitmap(self):
        rng = random.Random(301)
        # Separate byte/epoch occupancy oracle does not call live_overlap or
        # validate_placements; detect off-by-one lifetime/address errors directly.
        for trial in range(100):
            requests = tuple(
                BufferRequest(
                    str(i),
                    rng.randrange(0, 97),
                    1 << rng.randrange(0, 7),
                    (start := rng.randrange(-1, 10)),
                    rng.randrange(start, 12),
                    "scratch" if i % 3 == 0 else "activation",
                )
                for i in range(25)
            )
            p = first_fit(requests)
            offsets = {x.name: x.offset for x in p}
            occupied = {}
            capacity = 0
            for r in requests:
                if not r.size_bytes:
                    self.assertIsNone(offsets[r.name])
                    continue
                offset = offsets[r.name]
                self.assertEqual(offset % r.alignment, 0)
                capacity = max(capacity, offset + r.size_bytes)
                for epoch in range(r.start, r.end + 1):
                    for byte in range(offset, offset + r.size_bytes):
                        self.assertNotIn((epoch, byte), occupied, (trial, r.name))
                        occupied[epoch, byte] = r.name
            validate_placements(requests, p, capacity)
            shuffled = list(requests)
            rng.shuffle(shuffled)
            self.assertEqual(p, first_fit(tuple(shuffled)))


class GraphMemoryTests(unittest.TestCase):
    def setUp(self):
        self.graph = residual_graph()
        self.prepared = prepare_graph(self.graph)
        self.contracts = reference_memory_contracts(self.graph)

    def test_residual_lifetimes_and_output_handoff(self):
        plan = plan_memory(self.graph, self.prepared, self.contracts)
        self.assertEqual(
            (
                plan.tensors[2].producer,
                plan.tensors[2].first_use,
                plan.tensors[2].last_consumer,
                plan.tensors[2].start,
                plan.tensors[2].end,
            ),
            (0, 1, 2, 0, 2),
        )
        self.assertEqual((plan.tensors[0].start, plan.tensors[0].end), (-1, 0))
        self.assertEqual((plan.tensors[4].start, plan.tensors[4].end), (2, 3))
        self.assertEqual(plan.summary["timeline"][-1]["tensors"], [4])
        self.assertNotEqual(plan.tensors[2].offset, plan.tensors[4].offset)
        self.assertEqual(plan.tensors[1].offset, plan.tensors[4].offset)

    def test_multiple_external_outputs_and_optional_input_preservation(self):
        graph = import_bytes(
            build_model(
                tuple(T((1, 8)) for _ in range(5)),
                (
                    O("ADD", (0, 1), (2,)),
                    O("ADD", (2, 1), (3,)),
                    O("ADD", (3, 2), (4,)),
                ),
                inputs=(0, 1),
                outputs=(2, 4),
            )
        )
        plan = plan_memory(graph, options=MemoryOptions(preserve_inputs=True))
        self.assertEqual([plan.tensors[i].end for i in (0, 1, 2, 4)], [3] * 4)
        self.assertEqual(set(plan.summary["timeline"][-1]["tensors"]), {0, 1, 2, 4})

    def test_unused_graph_input_initialized_before_inference(self):
        tensors = tuple(T((1, 8)) for _ in range(4))
        graph = import_bytes(
            build_model(tensors, (O("ADD", (0, 1), (3,)),), inputs=(0, 1, 2))
        )
        plan = plan_memory(graph)
        unused = plan.tensors[2]
        self.assertEqual(
            (unused.first_use, unused.last_consumer, unused.start, unused.end),
            (None, None, -1, -1),
        )
        self.assertIn(2, plan.summary["timeline"][0]["tensors"])

    def test_reshape_alias_chains_extend_physical_lifetime(self):
        graph = reshape_chain()
        plan = plan_memory(graph)
        self.assertEqual(plan.arena_bytes, 16)
        self.assertTrue(all(a.enabled for a in plan.aliases))
        self.assertEqual({t.group for t in plan.tensors}, {"tensor:0"})
        self.assertEqual({t.offset for t in plan.tensors}, {0})
        self.assertEqual([(r.start, r.end) for r in plan.requests], [(-1, 3)])
        self.assertEqual([t.alias_of for t in plan.tensors], [None, 0, 1, 2])
        self.assertEqual(plan.summary["peak_live_activation_bytes"], 8)

    def test_alias_and_source_used_in_parallel_branches(self):
        tensors = tuple(T((1, 8)) for _ in range(5))
        graph = import_bytes(
            build_model(
                tensors,
                (
                    O("RESHAPE", (0,), (1,), options={"new_shape": (1, 8)}),
                    O("ADD", (1, 2), (3,)),
                    O("ADD", (0, 3), (4,)),
                ),
                inputs=(0, 2),
            )
        )
        plan = plan_memory(graph)
        self.assertEqual(plan.tensors[1].alias_of, 0)
        self.assertEqual(next(r.end for r in plan.requests if r.name == "tensor:0"), 2)
        self.assertNotEqual(plan.tensors[4].offset, plan.tensors[0].offset)

    def test_reshape_copy_policy_and_kernel_contract(self):
        graph = reshape_chain()
        for options, contracts in (
            (
                MemoryOptions(allow_reshape_views=False),
                reference_memory_contracts(graph),
            ),
            (
                MemoryOptions(),
                replace(
                    reference_memory_contracts(graph),
                    nodes=tuple(
                        replace(c, reshape_view=False)
                        for c in reference_memory_contracts(graph).nodes
                    ),
                ),
            ),
        ):
            plan = plan_memory(graph, contracts=contracts, options=options)
            self.assertFalse(any(a.enabled for a in plan.aliases))
            self.assertTrue(all(t.alias_of is None for t in plan.tensors))
            for node in graph.nodes:
                self.assertNotEqual(
                    plan.tensors[node.input("input")].offset,
                    plan.tensors[node.outputs[0]].offset,
                )

    def test_view_denied_if_later_consumer_can_write_source_or_view(self):
        graph = reshape_chain()
        contracts = reference_memory_contracts(graph)
        middle = contracts.nodes[1]
        contracts = override(
            contracts,
            1,
            inputs=(replace(middle.inputs[0], access="read_write"), middle.inputs[1]),
        )
        plan = plan_memory(graph, contracts=contracts)
        self.assertFalse(plan.aliases[0].enabled)
        self.assertIn("can write", plan.aliases[0].reason)
        self.assertNotEqual(plan.tensors[0].group, plan.tensors[1].group)

    def test_constant_source_reshape_copies_to_writable_storage(self):
        tensors = (T((1, 8)), T((1, 8), data=bytes(8)), T((1, 8)))
        graph = import_bytes(
            build_model(
                tensors, (O("RESHAPE", (1,), (2,), options={"new_shape": (1, 8)}),)
            )
        )
        plan = plan_memory(graph)
        self.assertFalse(plan.aliases[0].enabled)
        self.assertEqual(plan.tensors[1].section, ".rodata")
        self.assertEqual(plan.tensors[2].section, ".bss")

    def test_group_alignment_stricter_at_a_later_view_consumer(self):
        graph = reshape_chain()
        contracts = reference_memory_contracts(graph)
        final = contracts.nodes[2]
        contracts = override(
            contracts,
            2,
            inputs=(replace(final.inputs[0], alignment=128), final.inputs[1]),
        )
        plan = plan_memory(graph, contracts=contracts)
        self.assertEqual(
            (plan.arena_alignment, plan.arena_bytes, plan.requests[0].alignment),
            (128, 128, 128),
        )

    def test_conditional_scratch_shared_across_nodes_and_separate_at_same_node(self):
        scratch = (
            ScratchRequirement("one", 33, 32),
            ScratchRequirement("two", 17, 16),
            ScratchRequirement(
                "disabled", 100000, 4096, False, "INT4-only; actual weights INT8"
            ),
            ScratchRequirement("zero", 0, 64),
        )
        contracts = override(self.contracts, 0, scratch=scratch)
        contracts = override(
            contracts, 2, scratch=(ScratchRequirement("later", 33, 32),)
        )
        plan = plan_memory(self.graph, self.prepared, contracts)
        a, b, disabled, zero, later = plan.scratch
        self.assertEqual(a.offset, later.offset)
        self.assertNotEqual(a.offset, b.offset)
        self.assertEqual((disabled.offset, zero.offset), (None, None))
        self.assertEqual(
            [(s.start, s.end) for s in plan.scratch], [(0, 0)] * 4 + [(2, 2)]
        )
        self.assertEqual(plan.summary["peak_live_scratch_bytes"], 50)
        self.assertNotIn(disabled.group, {r.name for r in plan.requests})
        for s in (a, b):
            for t in plan.tensors:
                if t.start <= s.node <= t.end:
                    self.assertTrue(
                        s.offset + s.size_bytes <= t.offset
                        or t.offset + t.size_bytes <= s.offset
                    )

    def test_optional_bias_and_parameter_rodata_layout(self):
        tensors, (node,) = conv_fixture()
        tensors = (
            *tensors[:2],
            replace(tensors[2], data=struct.pack("<ii", -17, 31)),
            tensors[3],
        )
        # Omitted optional operand has no phantom allocation or request.
        data = build_model(
            (tensors[0], tensors[1], tensors[3]),
            (replace(node, inputs=(0, 1), outputs=(2,)),),
        )
        graph = import_bytes(data)
        prepared = prepare_graph(graph)
        plan = plan_memory(graph, prepared)
        self.assertEqual(len(plan.tensors), 3)
        self.assertEqual(
            [t.tensor for t in plan.tensors if t.section == ".rodata"], [1]
        )
        fields = plan.parameters[0].fields
        self.assertEqual([f[0] for f in fields], sorted(prepared.nodes[0].integers))
        self.assertEqual(sum(f[2] * 4 for f in fields), plan.parameters[0].size_bytes)
        self.assertEqual(plan.parameters[0].offset % 4, 0)

    def test_zero_scratch_does_not_inflate_base_alignment_or_budget(self):
        baseline = plan_memory(self.graph, self.prepared, self.contracts)
        contracts = override(
            self.contracts, 0, scratch=(ScratchRequirement("zero", 0, 4096),)
        )
        plan = plan_memory(
            self.graph,
            self.prepared,
            contracts,
            MemoryOptions(workspace_budget_bytes=baseline.arena_bytes),
        )
        self.assertEqual(
            (plan.arena_bytes, plan.arena_alignment),
            (baseline.arena_bytes, baseline.arena_alignment),
        )
        self.assertIsNone(plan.scratch[0].offset)

    def test_invalid_contracts_rejected_before_allocation(self):
        base = self.contracts.nodes[0]
        for changes in (
            {"node": 9},
            {"kind": "CONV_2D"},
            {"reshape_view": True},
            {"output_alignments": (3,)},
            {"inputs": base.inputs[:-1]},
            {"scratch": (ScratchRequirement("x", -1),)},
            {"scratch": (ScratchRequirement("x", 1, enabled=None),)},
            {"scratch": (ScratchRequirement("x", 1), ScratchRequirement("x", 2))},
        ):
            with self.subTest(changes=changes), self.assertRaises(ModelError):
                plan_memory(
                    self.graph, self.prepared, override(self.contracts, 0, **changes)
                )

    def test_zero_sized_tensor_rejected_by_graph_contract(self):
        with self.assertRaisesRegex(ModelError, "positive static shapes"):
            import_bytes(
                build_model(
                    (T((1, 0)), T((1, 0)), T((1, 0))),
                    (O("ADD", (0, 1), (2,)),),
                    inputs=(0, 1),
                )
            )

    def test_budgets_exact_fit_failures_and_unknown_stack(self):
        plan = plan_memory(self.graph, self.prepared, self.contracts)
        exact = plan_memory(
            self.graph,
            self.prepared,
            self.contracts,
            MemoryOptions(
                workspace_budget_bytes=plan.arena_bytes,
                rodata_budget_bytes=plan.rodata_bytes,
                stack_reserve_bytes=4096,
            ),
        )
        self.assertEqual(
            exact.summary["workspace_plus_explicit_stack_reserve_bytes"],
            plan.arena_bytes + 4096,
        )
        self.assertIsNone(exact.summary["stack_peak_bytes"])
        self.assertIsNone(exact.summary["total_target_ram_bytes"])
        for options in (
            MemoryOptions(workspace_budget_bytes=plan.arena_bytes - 1),
            MemoryOptions(rodata_budget_bytes=plan.rodata_bytes - 1),
            MemoryOptions(workspace_budget_bytes=-1),
            MemoryOptions(arena_alignment=3),
        ):
            with self.subTest(options=options), self.assertRaises(ModelError):
                plan_memory(self.graph, self.prepared, self.contracts, options)

    def test_serialized_plan_revalidates_lifetimes_aliases_addresses_and_summary(self):
        plan = plan_memory(self.graph, self.prepared, self.contracts)
        self.assertEqual(
            MemoryPlan.from_json(
                plan.to_json(), self.graph, self.prepared, self.contracts
            ),
            plan,
        )
        for mutate in (
            lambda d: d["tensors"][2].update(end=0),
            lambda d: d["requests"][0].update(end=-1),
            lambda d: d["placements"][0].update(offset=100000),
            lambda d: d["tensors"][2].update(alias_of=0),
            lambda d: d["summary"].update(peak_live_workspace_bytes=0),
            lambda d: d.update(kernel_memory_sha256="0" * 64),
        ):
            data = json.loads(plan.to_json())
            mutate(data)
            with self.assertRaises(ModelError):
                MemoryPlan.from_json(
                    json.dumps(data), self.graph, self.prepared, self.contracts
                )

    def test_export_determinism_hashes_chart_and_no_partial_budget_failure(self):
        plan = plan_memory(self.graph, self.prepared, self.contracts)
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "a", Path(directory) / "b"
            for output in (a, b):
                manifest = export_memory(
                    self.graph, self.prepared, self.contracts, plan, output
                )
                self.assertFalse(manifest["capabilities"]["inference_codegen"])
                for name, digest in manifest["artifacts"].items():
                    self.assertEqual(
                        hashlib.sha256((output / name).read_bytes()).hexdigest(), digest
                    )
            for name in manifest["artifacts"]:
                self.assertEqual((a / name).read_bytes(), (b / name).read_bytes())
            chart = json.loads((a / "memory_lifetimes.json").read_text())
            self.assertEqual(chart["epochs"]["intervals"], "inclusive")
            self.assertEqual(len(chart["tensors"]), 5)
            invalid = replace(
                plan, options=replace(plan.options, workspace_budget_bytes=0)
            )
            with self.assertRaisesRegex(ModelError, "budget exceeded"):
                export_memory(
                    self.graph,
                    self.prepared,
                    self.contracts,
                    invalid,
                    Path(directory) / "failure",
                )
            self.assertFalse((Path(directory) / "failure").exists())


class RealModelMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ROOT / "models/efficientnet-lite0-int8.tflite"
        cls.graph = import_model(cls.model)
        cls.prepared = prepare_graph(cls.graph)
        cls.contracts = reference_memory_contracts(cls.graph)
        cls.plan = plan_memory(cls.graph, cls.prepared, cls.contracts)

    def test_actual_workspace_and_readonly_accounting(self):
        self.assertEqual(self.plan.arena_bytes, 1505280)
        self.assertEqual(self.plan.rodata_bytes, 4867424)
        self.assertEqual(self.plan.summary["constant_tensor_bytes"], 4697032)
        self.assertEqual(sum(p.size_bytes for p in self.plan.parameters), 42598 * 4)
        self.assertEqual(
            self.plan.summary["runtime_tensor_bytes_without_reuse"], 7254424
        )
        self.assertEqual(
            self.plan.summary["peak_live_workspace_bytes"], self.plan.arena_bytes
        )
        self.assertEqual(self.plan.scratch, ())
        self.assertEqual(self.plan.summary["b0_total_arena_used_bytes"], 1688176)
        self.assertIn(
            "persistent interpreter metadata", self.plan.summary["b0_comparison"]
        )

    def test_actual_residual_last_consumer_and_reshape_proof(self):
        self.assertEqual(
            (
                self.plan.tensors[107].producer,
                self.plan.tensors[107].first_use,
                self.plan.tensors[107].last_consumer,
            ),
            (6, 7, 10),
        )
        self.assertEqual(
            (self.plan.tensors[160].alias_of, self.plan.tensors[161].alias_of),
            (None, 160),
        )
        group = next(r for r in self.plan.requests if r.name == "tensor:160")
        self.assertEqual((group.start, group.end, group.size_bytes), (59, 61, 1280))
        self.assertEqual(
            (self.plan.tensors[164].start, self.plan.tensors[164].end), (-1, 0)
        )
        self.assertEqual(
            (self.plan.tensors[165].start, self.plan.tensors[165].end), (63, 64)
        )

    def test_actual_all_epochs_independent_tensor_and_scratch_collision_check(self):
        for epoch in range(-1, 65):
            live = [
                t
                for t in self.plan.tensors
                if t.section == ".bss" and t.start <= epoch <= t.end
            ]
            for i, a in enumerate(live):
                for b in live[i + 1 :]:
                    if {a.tensor, b.tensor} == {160, 161}:
                        self.assertEqual(
                            (a.offset, a.size_bytes), (b.offset, b.size_bytes)
                        )
                    else:
                        self.assertTrue(
                            a.offset + a.size_bytes <= b.offset
                            or b.offset + b.size_bytes <= a.offset,
                            (epoch, a.tensor, b.tensor),
                        )
        audit = validate_memory_plan(
            self.plan, self.graph, self.prepared, self.contracts
        )
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["proven_views"], 1)

    def test_cli_with_prepared_ir_and_failing_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "success"
            prepared = Path(directory) / "prepared.json"
            prepared.write_text(self.prepared.to_json())
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = main(
                    [
                        "plan-memory",
                        str(self.model),
                        "--prepared-ir",
                        str(prepared),
                        "--output-dir",
                        str(output),
                        "--workspace-budget-bytes",
                        "2097152",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("1,505,280", stdout.getvalue())
            self.assertTrue((output / "memory_plan.json").exists())
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                code = main(
                    [
                        "plan-memory",
                        str(self.model),
                        "--output-dir",
                        str(Path(directory) / "failure"),
                        "--workspace-budget-bytes",
                        "1200000",
                    ]
                )
            self.assertEqual(code, 1)
            self.assertIn("workspace budget exceeded", stderr.getvalue())
            self.assertFalse((Path(directory) / "failure").exists())


if __name__ == "__main__":
    unittest.main()
