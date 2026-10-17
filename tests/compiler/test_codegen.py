"""Stage 4: deterministic generation plus complete, actually executed A0 evidence."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from compiler.cli import main
from compiler.emit_cpp import emit_cpp
from compiler.frontend import import_model
from compiler.ir import ModelError
from compiler.kernel_plan import ScratchRequirement
from compiler.lowering import lower_graph
from compiler.memory_plan import MemoryOptions, plan_memory
from compiler.oracle import verify_golden
from tools.build_a0 import (
    GENERATED,
    build,
    compare_case,
    verify_build,
    verify_generation,
)


def read(path):
    return json.loads(path.read_text())


class CodeGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = import_model(ROOT / "models/efficientnet-lite0-int8.tflite")
        cls.lowered = lower_graph(cls.graph)
        cls.manifest = verify_generation(GENERATED)

    def test_generation_has_all_64_nodes_constants_memory_and_source_map(self):
        mapping = read(GENERATED / "source_map.json")
        lines = (GENERATED / "model.cc").read_text().splitlines()
        self.assertEqual([n["node"] for n in mapping["nodes"]], list(range(64)))
        self.assertEqual(mapping["inference_symbol"], "a0_invoke")
        for record, original in zip(mapping["nodes"], self.graph.nodes):
            self.assertIn(record["symbol"] + "()", lines[record["line"] - 1])
            self.assertEqual(lines[record["end_line"] - 1], "}")
            self.assertEqual(record["outputs"], list(original.outputs))
        self.assertEqual(
            self.manifest["memory_plan_sha256"], self.lowered.memory.sha256
        )
        self.assertFalse(self.manifest["capabilities"]["optimized_kernels"])

    def test_generation_deterministic_across_output_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "moved"
            candidate = emit_cpp(self.lowered, output)
            self.assertEqual(self.manifest["artifacts"], candidate["artifacts"])
            for name in candidate["artifacts"]:
                self.assertEqual(
                    (GENERATED / name).read_bytes(), (output / name).read_bytes()
                )

    def test_cli_generates_only_audited_A0(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            prepared = Path(directory) / "prepared.json"
            memory = Path(directory) / "memory.json"
            prepared.write_text(self.lowered.prepared.to_json())
            supplied_plan = plan_memory(
                self.graph,
                self.lowered.prepared,
                options=MemoryOptions(allow_reshape_views=False),
            )
            memory.write_text(supplied_plan.to_json())
            self.assertEqual(
                main(
                    [
                        "generate",
                        str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                        "--config",
                        "A0",
                        "--prepared-ir",
                        str(prepared),
                        "--memory-plan",
                        str(memory),
                        "--output-dir",
                        directory,
                    ]
                ),
                0,
            )
            self.assertIn("64 nodes", stdout.getvalue())
            self.assertEqual(
                read(Path(directory) / "manifest.json")["configuration"], "A0"
            )
            self.assertEqual(
                read(Path(directory) / "manifest.json")["memory_plan_sha256"],
                supplied_plan.sha256,
            )
            invalid = read(memory)
            invalid["arena_bytes"] = 1
            memory.write_text(json.dumps(invalid))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "generate",
                            str(ROOT / "models/efficientnet-lite0-int8.tflite"),
                            "--memory-plan",
                            str(memory),
                            "--output-dir",
                            str(Path(directory) / "rejected"),
                        ]
                    ),
                    1,
                )
            self.assertFalse((Path(directory) / "rejected").exists())

    def test_lowering_rejects_forged_parameters_and_storage(self):
        prepared = self.lowered.prepared
        first = prepared.nodes[0]
        changed = replace(
            first, integers={**first.integers, "requantize_output_multiplier": 1}
        )
        with self.assertRaises(ModelError):
            lower_graph(
                self.graph, replace(prepared, nodes=(changed, *prepared.nodes[1:]))
            )
        with self.assertRaises(ModelError):
            lower_graph(self.graph, memory=replace(self.lowered.memory, arena_bytes=1))

    def test_lowering_rejects_unimplemented_scratch_kernel_contract(self):
        contracts = self.lowered.contracts
        node = replace(
            contracts.nodes[1], scratch=(ScratchRequirement("unimplemented", 1024),)
        )
        memory = plan_memory(
            self.graph,
            self.lowered.prepared,
            replace(contracts, nodes=(contracts.nodes[0], node, *contracts.nodes[2:])),
        )
        with self.assertRaises(ModelError):
            lower_graph(self.graph, self.lowered.prepared, memory)

    def test_copy_and_large_alignment_variant_complete_baseline_arrays(self):
        memory = plan_memory(
            self.graph,
            self.lowered.prepared,
            options=MemoryOptions(arena_alignment=128, allow_reshape_views=False),
        )
        lowered = lower_graph(self.graph, self.lowered.prepared, memory)
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory)
            emit_cpp(lowered, generated)
            record = build(generated, "capture")
            output = generated / "run"
            output.mkdir()
            oracle = Path(read(ROOT / "build/compiler/oracle/latest.json")["capture"])
            reference = verify_golden(
                oracle, ROOT / "tests/compiler/fixtures/oracle-golden.json"
            )
            result = subprocess.run(
                [
                    str(ROOT / record["binary"]),
                    str(oracle / "baseline/input.bin"),
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
            )
            self.assertEqual(result.stderr, "")
            self.assertEqual(
                compare_case(oracle / "baseline", output, reference["cases"][0]), 64
            )

    def test_modified_artifact_rejected_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            # Only copy generator artifacts, not executables/capture directories.
            for name in ["manifest.json", *self.manifest["artifacts"]]:
                shutil.copy2(GENERATED / name, output / name)
            with (output / "constants.cc").open("r+b") as file:
                file.write(b"?")
            with self.assertRaisesRegex(ModelError, "generated artifact changed"):
                verify_generation(output)


class ExecutedA0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = Path(read(ROOT / "build/compiler/oracle/latest.json")["capture"])
        cls.reference = verify_golden(
            cls.oracle, ROOT / "tests/compiler/fixtures/oracle-golden.json"
        )
        cls.records = {
            kind: verify_build(GENERATED, kind)
            for kind in ("capture", "sanitized", "native", "rv64")
        }

    def test_all_native_and_sanitized_complete_node_arrays(self):
        for kind in ("capture", "sanitized"):
            report = read(GENERATED / kind / "differential.json")
            self.assertEqual(
                report["binary_sha256"], self.records[kind]["binary_sha256"]
            )
            self.assertEqual(report["complete_node_arrays_compared"], 510)
            self.assertEqual(report["status"], "PASS")
            for case, evidence in zip(self.reference["cases"], report["cases"]):
                with self.subTest(kind=kind, case=case["name"]):
                    directory = GENERATED / kind / "captures" / case["name"]
                    self.assertEqual(
                        compare_case(self.oracle / case["name"], directory, case),
                        case["expected_nodes"],
                    )
                    for name, digest in evidence["files"].items():
                        self.assertEqual(
                            hashlib.sha256((directory / name).read_bytes()).hexdigest(),
                            digest,
                        )
                    self.assertEqual((directory / "stderr.txt").read_text(), "")

    def test_release_native_full_public_outputs_and_error_domain(self):
        report = read(GENERATED / "native/differential.json")
        self.assertEqual(
            report["binary_sha256"], self.records["native"]["binary_sha256"]
        )
        for case in self.reference["cases"]:
            compare_case(
                self.oracle / case["name"],
                GENERATED / "native/captures" / case["name"],
                case,
                captured=False,
            )

    def test_array_comparison_reports_first_divergent_node_and_byte(self):
        case = self.reference["cases"][0]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "corrupt"
            shutil.copytree(GENERATED / "capture/captures/baseline", target)
            node = case["tensors"][4]
            with (target / node["file"]).open("r+b") as file:
                file.seek(19)
                value = file.read(1)[0]
                file.seek(19)
                file.write(bytes([value ^ 1]))
            with self.assertRaisesRegex(ModelError, "first divergent node 4.*byte 19"):
                compare_case(self.oracle / "baseline", target, case)

    def test_no_interpreter_and_capture_hooks_absent_from_release(self):
        for kind, record in self.records.items():
            text = (GENERATED / kind / "symbols.txt").read_text()
            self.assertNotIn("MicroInterpreter", text)
            self.assertNotIn("MicroAllocator", text)
            self.assertEqual(len(record["stable_node_symbols"]), 64)
            if kind in ("native", "rv64"):
                self.assertNotIn("a0_set_capture", text)
                self.assertNotIn("a0_debug_guard", text)

    def test_guards_detect_corruption_before_execution(self):
        for kind in ("capture", "sanitized"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run(
                    [
                        str(ROOT / self.records[kind]["binary"]),
                        "-",
                        directory,
                        "--corrupt-guard",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 3, result.stderr)
                data = read(Path(directory) / "result.json")
                self.assertEqual(data["captured_nodes"], 0)
                self.assertFalse(data["guards"])
                self.assertFalse((Path(directory) / "output.bin").exists())

    def test_short_and_oversized_input_rejected(self):
        for size in (150527, 150529):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                data = root / "bad-input.bin"
                data.write_bytes(bytes(size))
                result = subprocess.run(
                    [
                        str(ROOT / self.records["capture"]["binary"]),
                        str(data),
                        directory,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 11)
                self.assertFalse((root / "output.bin").exists())

    def test_recovery_after_softmax_error_reuses_workspace_safely(self):
        case = next(c for c in self.reference["cases"] if c["name"] == "zero_point")
        for kind in ("capture", "sanitized"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run(
                    [
                        str(ROOT / self.records[kind]["binary"]),
                        str(self.oracle / "zero_point/input.bin"),
                        directory,
                        "--recover",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=120,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(
                    compare_case(self.oracle / "zero_point", Path(directory), case), 62
                )
                self.assertEqual(
                    (Path(directory) / "recovered-output.bin").read_bytes(),
                    (ROOT / "tests/compiler/fixtures/baseline-output.bin").read_bytes(),
                )

    def test_rv64_full_output_isa_stack_and_section_evidence(self):
        record = self.records["rv64"]
        report = read(GENERATED / "rv64/spike-verification.json")
        self.assertEqual(report["binary_sha256"], record["binary_sha256"])
        self.assertEqual(report["full_output_bytes_compared"], 1000)
        self.assertIn("RV64IMC ELF audit: PASS", record["isa_audit"])
        self.assertIn(
            "forbidden floating/vector/atomic instructions: 0", record["isa_audit"]
        )
        self.assertGreater(report["stack_watermark_bytes"], 0)
        self.assertLess(report["stack_watermark_bytes"], 1048576)
        self.assertGreaterEqual(record["section_sizes"][".bss"], 1505280)
        self.assertGreaterEqual(record["section_sizes"][".rodata"], 4867424)
        self.assertTrue((GENERATED / "rv64/stack-frames.json").exists())


if __name__ == "__main__":
    unittest.main()
