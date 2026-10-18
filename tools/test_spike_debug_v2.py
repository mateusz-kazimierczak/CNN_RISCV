"""Compiler execution schedules, v2 validation, and real accepted-B1 debug gates."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.profile_spike import symbols
from tools.spike_debug.evidence import execution_schedule, read_bundle
from tools.spike_debug.server import MODEL, ROOT, Configuration, Native, Session

SPIKE = ROOT / ".deps/spike-debug/bin/spike"
B1_BUNDLE = ROOT / "build/explorer/B1-spatial2-oc2.zip"
B1_ELF = ROOT / "build/compiler/B1-spatial2-oc2/rv64/a0.elf"


class CompiledNativeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.natives, self.sessions, self.records = [], [], []

    async def asyncTearDown(self):
        for s in self.sessions:
            await s.close()
        for n in self.natives:
            await n.close()
        self.temp.cleanup()

    async def emit(self, record):
        self.records.append(record)

    def fixture(self, define=None):
        from tools.test_spike_debug import DebugTests

        helper = DebugTests()
        helper.directory = Path(self.temp.name)
        c, names = helper.fixture(define)
        # No allocation event, graph object or DWARF layout. Three observations
        # share the same compiled function, with a fused and split origin fixture.
        c.native_config.write_text(
            f"execution compiler\nregion invoke {names['invoke']:#x}\n"
            + "".join(f"unit {i} u{i} {names['toy_operator']:#x}\n" for i in range(3))
        )
        c.nodes = [{"id": str(i), "index": i} for i in range(4)]
        c.stages = [
            {"index": i, "id": f"u{i}", "nodes": ns}
            for i, ns in enumerate([["0", "1"], ["1"], ["2"]])
        ]
        return c, names

    async def native(self, define=None):
        c, names = self.fixture(define)
        n = Native(c, 1, self.emit)
        self.natives.append(n)
        await n.launch()
        root = (await n.command("run"))["snapshot"]
        self.assertEqual(root["reason"], "inference-entry")
        return c, n, names, int(root["retired"])

    async def test_hand_counted_shared_entries_callees_compressed_and_return(self):
        _, n, names, begin = await self.native()
        await n.command("target", 0)
        first = (await n.command("run"))["snapshot"]
        self.assertEqual(first["node"], 0)
        self.assertEqual(int(first["pc"]), names["toy_operator"])
        await n.command("target", 1)
        second = (await n.command("run"))["snapshot"]
        # Each unit is 17 instructions; caller between entries is four.
        self.assertEqual(int(second["retired"]) - int(first["retired"]), 21)
        self.assertEqual(second["node"], 1)
        complete = (await n.command("run"))["snapshot"]
        self.assertEqual(complete["reason"], "inference-complete")
        self.assertEqual(complete["node"], -1)
        self.assertEqual(complete["entered"], 2)
        # 3 * 17 unit instructions plus 22 invocation/caller instructions.
        self.assertEqual(int(complete["retired"]) - begin, 73)

    async def test_session_exposes_shared_origins_and_unit_breakpoints(self):
        c, names = self.fixture()
        session = Session(c, self.emit)
        self.sessions.append(session)
        await session.execute({"requestId": 1, "command": "start"})
        await session.execute(
            {"requestId": 2, "generation": 1, "command": "stage", "unit": 0}
        )
        public = self.records[-1]["snapshot"]
        self.assertEqual(public["unitId"], "u0")
        self.assertEqual(public["unitIndex"], 0)
        self.assertEqual(public["nodeIds"], ["0", "1"])
        self.assertEqual(public["node"], -1)  # a shared unit is not one logical node
        await session.execute(
            {
                "requestId": 3,
                "generation": 1,
                "command": "breakpoint",
                "key": 7,
                "unit": 1,
            }
        )
        await session.execute({"requestId": 4, "generation": 1, "command": "continue"})
        self.assertEqual(session.snapshot["reason"], "breakpoint")
        self.assertEqual(self.records[-1]["snapshot"]["unitId"], "u1")
        self.assertEqual(self.records[-1]["snapshot"]["nodeIds"], ["1"])
        self.assertEqual(int(session.snapshot["pc"]), names["toy_operator"])
        with self.assertRaises(ValueError):
            await session.execute(
                {"requestId": 5, "generation": 1, "command": "stage", "unit": 3}
            )
        await session.execute(
            {"requestId": 6, "generation": 1, "command": "stage", "unit": 0}
        )
        self.assertEqual(session.generation, 2)
        self.assertEqual(session.snapshot["node"], 0)

    async def test_compiler_trap_and_serialization_keep_retirement_guarantees(self):
        _, n, names, _ = await self.native("TRAP")
        await n.command("break", 1, names["trap_instruction"], -1)
        before = (await n.command("run"))["snapshot"]
        trap = (await n.command("step"))["snapshot"]
        self.assertEqual(trap["reason"], "trap")
        self.assertEqual(trap["retired"], before["retired"])
        _, n, _, _ = await self.native("SERIALIZE")
        await n.command("target", 0)
        before = (await n.command("run"))["snapshot"]
        for _ in range(3):
            after = (await n.command("step"))["snapshot"]
        self.assertEqual(int(after["retired"]) - int(before["retired"]), 3)
        self.assertGreater(
            int(after["serializationRetries"]), int(before["serializationRetries"])
        )

    async def test_unexpected_unit_order_fails_closed(self):
        c, names = self.fixture()
        text = c.native_config.read_text().replace(
            f"unit 0 u0 {names['toy_operator']:#x}", f"unit 0 u0 {names['helper']:#x}"
        )
        c.native_config.write_text(text)
        n = Native(c, 1, self.emit)
        self.natives.append(n)
        await n.launch()
        await n.command("run")
        stopped = (await n.command("run"))["snapshot"]
        self.assertEqual(stopped["reason"], "attribution-error")
        self.assertIn("entry/order", stopped["error"])

    async def test_tail_return_closes_the_unit_at_its_callers_return(self):
        _, n, _, begin = await self.native("TAIL")
        complete = (await n.command("run"))["snapshot"]
        self.assertEqual(complete["reason"], "inference-complete")
        self.assertEqual(int(complete["retired"]) - begin, 34)  # 3 * 4 + 22

    async def test_missing_units_and_nonzero_return_cannot_complete(self):
        c, names = self.fixture()
        with c.native_config.open("a") as f:
            f.write(f"unit 3 missing {names['toy_operator']:#x}\n")
        n = Native(c, 1, self.emit)
        self.natives.append(n)
        await n.launch()
        await n.command("run")
        incomplete = (await n.command("run"))["snapshot"]
        self.assertEqual(incomplete["reason"], "attribution-error")
        self.assertFalse(incomplete["inferenceComplete"])
        _, n, _, _ = await self.native("BADSTATUS")
        failed = (await n.command("run"))["snapshot"]
        self.assertEqual(failed["reason"], "attribution-error")
        self.assertFalse(failed["inferenceComplete"])
        self.assertIn("nonzero status", failed["error"])


class OutputValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_matching_checksum_cannot_hide_wrong_or_incomplete_output(self):
        from types import SimpleNamespace

        expected = bytes(range(250)) * 4

        async def finished():
            return 0

        for payload in (expected, bytes(1000), expected[:-1], b""):
            records = []

            async def emit(message, records=records):
                records.append(message)

            config = SimpleNamespace(
                evidence={
                    "provenance": {
                        "output_fnv1a": "0x0",
                        "output_sha256": hashlib.sha256(expected).hexdigest(),
                    }
                }
            )
            session = Session(config, emit)
            session.native = SimpleNamespace(
                process=SimpleNamespace(wait=finished, returncode=0),
                tasks=[],
                output="output_fnv1a=0x0\noutput_hex=" + payload.hex() + "\n",
            )
            await session.stop(
                {"snapshot": {"reason": "exited", "inferenceComplete": True}}, 1
            )
            result = records[-1]
            self.assertEqual(result["passed"], payload == expected)
            self.assertEqual(
                result["outputBytesValidated"], 1000 if payload == expected else None
            )


@unittest.skipUnless(
    B1_BUNDLE.exists() and B1_ELF.exists(), "accepted B1 evidence required"
)
class V2ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = read_bundle(B1_BUNDLE)
        cls.syms = symbols(B1_ELF)

    def test_real_B1_and_B0_use_different_adapters(self):
        c = Configuration(B1_ELF, MODEL, B1_BUNDLE, SPIKE, "B1-spatial2-oc2")
        self.assertEqual(c.adapter, "compiler-v2")
        self.assertEqual(len(c.stages), 64)
        self.assertNotIn("allocate", c.native_text.decode())
        self.assertNotIn("graph ", c.native_text.decode())
        b0 = Configuration(
            ROOT
            / "build/tflm-profile/rv64imc_rv64imc_release_with_logs_gcc/bin/efficientnet_lite0",
            MODEL,
            ROOT / "build/explorer/B0.zip",
            SPIKE,
        )
        self.assertEqual(b0.adapter, "litert")
        self.assertIn("graph ", b0.native_text.decode())

    def test_rejects_failed_counts_mismatched_entries_and_unknown_instructions(self):
        variants = []
        d = copy.deepcopy(self.data)
        d["events"][1]["status"] = "2"
        variants.append(d)
        d = copy.deepcopy(self.data)
        d["events"][1]["complete"] = False
        variants.append(d)
        d = copy.deepcopy(self.data)
        d["events"][1]["entry"] = d["events"][2]["entry"]
        variants.append(d)
        d = copy.deepcopy(self.data)
        next(iter(d["events"][1]["counts"]))
        d["events"][1]["total"] = "18446744073709551616"
        variants.append(d)
        d = copy.deepcopy(self.data)
        d["executionPlan"]["units"][1]["eventIds"] = ["1"]
        variants.append(d)
        d = copy.deepcopy(self.data)
        pc = next(iter(d["events"][1]["counts"]))
        d["instructions"][pc]["mnemonic"] = "unknown"
        variants.append(d)
        for d in variants:
            with self.subTest(), self.assertRaises(ValueError):
                execution_schedule(d, B1_ELF, self.syms)

    def test_zip_integrity_schema_limits_and_paths(self):
        def packed(name, schema=2, digest=None):
            raw = b"{}"
            m = {
                "format": "riscv-execution-explorer",
                "schemaVersion": schema,
                "files": {
                    name: {
                        "size": 2,
                        "sha256": digest or hashlib.sha256(raw).hexdigest(),
                    }
                },
            }
            return {"manifest.json": json.dumps(m).encode(), name: raw}

        for payload in [
            packed("../evidence.json"),
            packed("evidence.json", 1),
            packed("evidence.json", digest="0" * 64),
        ]:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.zip"
                with zipfile.ZipFile(path, "w") as z:
                    for name, content in payload.items():
                        z.writestr(name, content)
                with self.assertRaises(ValueError):
                    read_bundle(path)


@unittest.skipUnless(
    os.environ.get("SPIKE_DEBUG_FULL_B1") == "1", "opt in to the full accepted B1 run"
)
class RealB1Tests(unittest.IsolatedAsyncioTestCase):
    async def test_full_count_output_breakpoint_and_replay(self):
        c = Configuration(B1_ELF, MODEL, B1_BUNDLE, SPIKE, "B1-spatial2-oc2")
        records = []

        async def emit(m):
            if m["type"] in ("stopped", "result", "reset"):
                records.append(m)

        session = Session(c, emit)
        request = 0

        async def command(op, **args):
            nonlocal request
            request += 1
            await session.execute(
                {
                    "requestId": request,
                    "generation": session.generation,
                    "command": op,
                    **args,
                }
            )

        try:
            await command("start")
            begin = int(session.snapshot["retired"])
            await command("stage", unit=0)
            before = int(session.snapshot["retired"])
            await command("step")
            self.assertEqual(int(session.snapshot["retired"]), before + 1)
            await command("stage", unit=1)
            self.assertEqual(records[-1]["snapshot"]["unitId"], "node:1")
            await command("breakpoint", key=7, pc=str(c.stage_pcs[2]))
            await command("continue")
            self.assertEqual(session.snapshot["reason"], "breakpoint")
            self.assertEqual(int(session.snapshot["pc"]), c.stage_pcs[2])
            await command("breakpoint", key=7, remove=True)
            await command("continue")
            self.assertEqual(session.snapshot["reason"], "inference-complete")
            self.assertEqual(int(session.snapshot["retired"]) - begin, 1576585275)
            await command("continue")
            self.assertEqual(session.snapshot["reason"], "exited")
            self.assertTrue(records[-1]["passed"])
            self.assertEqual(records[-1]["outputBytesValidated"], 1000)
            await command("stage", unit=0)
            self.assertEqual(session.generation, 2)
            self.assertEqual(session.snapshot["node"], 0)
        finally:
            p = ROOT / "build/simulator/B1-spatial2-oc2/acceptance-v2.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(records, indent=2) + "\n")
            await session.close()


if __name__ == "__main__":
    unittest.main()
