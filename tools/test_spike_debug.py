"""Native machine-protocol, session replay, and loopback API integration tests."""

import asyncio, json, os, subprocess, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from tools.spike_debug.server import (
    Native,
    Session,
    Configuration,
    ROOT,
    MODEL,
    unsigned,
    application,
)
from tools.profile_spike import disassemble
from aiohttp.test_utils import TestClient, TestServer

PREFIX = ROOT / ".deps/xpack-riscv/bin/riscv-none-elf-"
SPIKE = ROOT / ".deps/spike-debug/bin/spike"


class DebugTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.messages = []
        self.natives = []
        self.sessions = []

    async def asyncTearDown(self):
        for s in self.sessions:
            await s.close()
        for n in self.natives:
            await n.close()
        self.temp.cleanup()

    async def emit(self, m):
        self.messages.append(m)

    def fixture(self, define=None):
        elf = self.directory / ("fixture" + (define or "") + ".elf")
        command = [
            str(PREFIX) + "gcc",
            "-nostdlib",
            "-nostartfiles",
            "-march=rv64imc_zicsr",
            "-mabi=lp64",
            "-Wl,-T," + str(ROOT / "tflm/platform/rv64imc/link.ld"),
            "-o",
            str(elf),
            str(ROOT / "tools/spike_debug/fixture.S"),
        ]
        if define:
            command.append("-D" + define)
        subprocess.run(command, check=True, capture_output=True)
        names = {
            parts[2]: int(parts[0], 16)
            for line in subprocess.check_output(
                [str(PREFIX) + "nm", "--defined-only", str(elf)], text=True
            ).splitlines()
            if len(parts := line.split()) == 3
        }
        config = self.directory / ("debug" + (define or "") + ".cfg")
        config.write_text(
            f"region invoke {names['invoke']:#x}\nregion allocate {names['allocate']:#x}\ngraph {names['graph_enter']:#x} 0 4\noperator ADD {names['toy_operator']:#x}\nnode 0 ADD\nnode 1 ADD\nnode 2 ADD\n"
        )
        return SimpleNamespace(
            elf=elf,
            spike=SPIKE,
            native_config=config,
            identity={},
            isa="rv64imc_zicsr",
            stage_pcs={i: names["toy_operator"] for i in range(3)},
            instructions={str(pc): {} for pc in disassemble(elf)},
            nodes=[{}] * 3,
            evidence={"provenance": {"output_fnv1a": "0x0"}},
        ), names

    async def native(self, define=None):
        config, names = self.fixture(define)
        n = Native(config, 1, self.emit)
        self.natives.append(n)
        await n.launch()
        m = await n.command("run")
        self.assertEqual(m["snapshot"]["reason"], "inference-entry")
        return n, names

    async def test_breakpoints_before_start_are_applied_and_can_be_removed_without_execution(self):
        config, names = self.fixture()
        s = Session(config, self.emit)
        self.sessions.append(s)
        await s.execute({"requestId": 1, "generation": 0, "command": "breakpoint", "key": 7, "pc": str(names["loop"])})
        self.assertIsNone(s.native)
        self.assertEqual(s.breakpoints[7]["pc"], str(names["loop"]))
        await s.execute({"requestId": 2, "generation": 0, "command": "breakpoint", "key": 8, "node": 2})
        await s.execute({"requestId": 3, "generation": 0, "command": "breakpoint", "key": 8, "remove": True})
        self.assertEqual(set(s.breakpoints), {7})
        await s.execute({"requestId": 4, "command": "start"})
        self.assertEqual(s.snapshot["reason"], "inference-entry")
        await s.execute({"requestId": 5, "generation": s.generation, "command": "continue"})
        self.assertEqual(int(s.snapshot["pc"]), names["loop"])
        self.assertEqual(s.snapshot["reason"], "breakpoint")
        before = dict(s.snapshot)
        await s.execute({"requestId": 6, "generation": s.generation, "command": "breakpoint", "key": 7, "remove": True})
        self.assertEqual(s.snapshot, before)
        self.assertFalse(s.breakpoints)

    async def test_reset_rom_window_is_bounded_and_does_not_execute_or_decode_data(self):
        config, names = self.fixture()
        n = Native(config, 1, self.emit)
        self.natives.append(n)
        ready = (await n.launch())["snapshot"]
        self.assertEqual(int(ready["pc"]), 0x1000)
        self.assertEqual(int(ready["retired"]), 0)
        window = ready["instructionWindow"]
        self.assertEqual([int(i["pc"]) for i in window], list(range(0x1000, 0x1014, 4)))
        self.assertTrue(all(i["length"] == 4 for i in window))
        repeated = (await n.command("snapshot"))["snapshot"]
        self.assertEqual(repeated["registers"], ready["registers"])
        self.assertEqual(int(repeated["retired"]), 0)
        for _ in range(5):
            stopped = (await n.command("step"))["snapshot"]
        self.assertEqual(int(stopped["pc"]), names["_start"])
        self.assertEqual(int(stopped["retired"]), 5)
        self.assertNotIn("instructionWindow", stopped)

    async def test_breakpoints_step_calls_compressed_and_reentry(self):
        n, names = await self.native()
        await n.command("break", 1, names["loop"], -1)
        m = await n.command("run")
        self.assertEqual(m["snapshot"]["node"], 0)
        start = int(m["snapshot"]["retired"])
        self.assertEqual(int(m["snapshot"]["registers"][5]), 3)
        m = await n.command("step")
        self.assertEqual(int(m["snapshot"]["registers"][5]), 2)
        self.assertEqual(int(m["snapshot"]["retired"]), start + 1)
        m = await n.command("run")
        self.assertEqual(int(m["snapshot"]["pc"]), names["loop"])
        self.assertEqual(int(m["snapshot"]["registers"][5]), 2)
        await n.command("delete", 1)
        await n.command("break", 2, names["helper"], 0)
        m = await n.command("run")
        self.assertEqual(m["snapshot"]["node"], 0)
        self.assertEqual(int(m["snapshot"]["registers"][10]), 7)
        await n.command("delete", 2)
        await n.command("target", 2)
        m = await n.command("run")
        self.assertEqual(m["snapshot"]["reason"], "stage-breakpoint")
        self.assertEqual(m["snapshot"]["node"], 2)

    async def test_trap_stops_before_handler_and_does_not_retire(self):
        n, names = await self.native("TRAP")
        await n.command("break", 1, names["trap_instruction"], -1)
        m = await n.command("run")
        before = m["snapshot"]["retired"]
        m = await n.command("step")
        self.assertEqual(m["snapshot"]["reason"], "trap")
        self.assertEqual(m["snapshot"]["retired"], before)
        self.assertEqual(int(m["snapshot"]["pc"]), names["trap_handler"])
        self.assertEqual(int(m["snapshot"]["trap"]["pc"]), names["trap_instruction"])

    async def test_serialization_retires_once_and_memory_is_read_only(self):
        n, names = await self.native("SERIALIZE")
        await n.command("target", 0)
        m = await n.command("run")
        before = int(m["snapshot"]["retired"])
        retries = int(m["snapshot"]["serializationRetries"])
        for _ in range(3):
            m = await n.command("step")
        self.assertEqual(int(m["snapshot"]["retired"]), before + 3)
        self.assertGreater(int(m["snapshot"]["serializationRetries"]), retries)
        m = await n.command("memory", names["graph_state"], 8)
        self.assertEqual(m["hex"], "0000000000000000")
        m = await n.command("memory", names["cross_page"], 6)
        self.assertEqual(m["hex"], "abcdef123456")
        for address, size in [
            (0x1000, 4),
            (0x10000000, 4),
            (0x87FFFFFF, 2),
            (0x80000000, 4097),
            (0x80000000, 0),
        ]:
            with self.assertRaises(ValueError):
                await n.command("memory", address, size)

    async def test_wait_reports_without_fabricated_retirement(self):
        n, _ = await self.native("WAIT")
        m = await n.command("run")
        self.assertEqual(m["snapshot"]["reason"], "wait")
        before = m["snapshot"]["retired"]
        m = await n.command("step")
        self.assertEqual(m["snapshot"]["reason"], "wait")
        self.assertEqual(m["snapshot"]["retired"], before)

    async def test_session_replay_keeps_breakpoints_and_destination(self):
        config, names = self.fixture()
        s = Session(config, self.emit)
        self.sessions.append(s)
        request = 0

        async def command(op, **kw):
            nonlocal request
            request += 1
            await s.execute(
                {"requestId": request, "generation": s.generation, "command": op, **kw}
            )

        await command("start")
        await command("stage", node=2)
        self.assertEqual(s.snapshot["node"], 2)
        generation = s.generation
        await command("breakpoint", key=7, node=0)
        await command("stage", node=1)
        self.assertEqual(s.generation, generation + 1)
        self.assertEqual(s.snapshot["node"], 0)
        self.assertEqual(s.target, 1)
        self.assertIn(7, s.breakpoints)
        await command("continue")
        self.assertEqual(s.snapshot["node"], 1)
        self.assertIsNone(s.target)
        with self.assertRaises(ValueError):
            await s.execute(
                {"requestId": 99, "generation": generation, "command": "step"}
            )

    async def test_replay_breakpoints_before_inference_and_retargeting(self):
        config, names = self.fixture()
        session = Session(config, self.emit)
        self.sessions.append(session)
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

        await command("start")
        await command("stage", node=2)
        await command("breakpoint", key=1, pc=str(names["allocate"]))
        await command("stage", node=0)
        self.assertEqual(int(session.snapshot["pc"]), names["allocate"])
        self.assertEqual(session.target, 0)
        await command("breakpoint", key=1, remove=True)
        await command("stage", node=1)
        self.assertEqual(session.snapshot["node"], 1)
        await command("breakpoint", key=2, pc=str(names["invoke"]))
        await command("stage", node=0)
        self.assertEqual(int(session.snapshot["pc"]), names["invoke"])
        self.assertEqual(session.target, 0)
        await command("breakpoint", key=2, remove=True)
        await command("continue")
        self.assertEqual(session.snapshot["node"], 0)
        self.assertIsNone(session.target)

    async def test_instruction_step_can_arrive_at_pending_stage_entry(self):
        config, names = self.fixture()
        session = Session(config, self.emit)
        self.sessions.append(session)
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

        await command("start")
        await command("breakpoint", key=1, pc=str(names["before_operator"]))
        await command("stage", node=0)
        self.assertEqual(session.target, 0)
        await command("step")
        await command("step")
        self.assertEqual(session.snapshot["node"], 0)
        self.assertEqual(session.snapshot["reason"], "step")
        self.assertIsNone(session.target)

    async def test_pause_and_disconnect_cleanup(self):
        config, _ = self.fixture("FOREVER")
        s = Session(config, self.emit)
        self.sessions.append(s)
        await s.execute({"requestId": 1, "command": "start"})
        n = s.native
        task = asyncio.create_task(n.command("run"))
        await asyncio.sleep(0.03)
        await asyncio.wait_for(n.command("pause"), 3)
        m = await asyncio.wait_for(task, 3)
        self.assertEqual(m["snapshot"]["reason"], "pause")
        self.assertIsNone(n.process.returncode)
        await s.close()
        self.assertIsNotNone(n.process.returncode)

    async def test_operator_index_mismatch_stops(self):
        config, _ = self.fixture()
        config.native_config.write_text(
            config.native_config.read_text()
            .replace("graph ", "graph ", 1)
            .replace(" 0 4\n", " 4 0\n")
        )
        n = Native(config, 1, self.emit)
        self.natives.append(n)
        await n.launch()
        await n.command("run")
        await n.command("target", 1)
        m = await n.command("run")
        self.assertEqual(m["snapshot"]["reason"], "attribution-error")

    async def test_unified_app_serves_explorer_and_profile_without_debug_artifacts(self):
        dist = self.directory / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("centralized explorer")
        (dist / "simulator.html").write_text("legacy simulator entry")
        bundle = self.directory / "configured.zip"
        bundle.write_bytes(b"configured profile")
        client = TestClient(TestServer(application(
            None, "Missing debug ELF", dist, bundle, "fixture",
        )))
        await client.start_server()
        try:
            self.assertEqual(await (await client.get("/")).text(), "centralized explorer")
            self.assertEqual(await (await client.get("/simulator.html")).text(), "legacy simulator entry")
            descriptor = await (await client.get("/local-profile.json")).json()
            self.assertEqual(descriptor, {
                "available": True, "configuration": "fixture", "url": "/profiles/local.zip",
            })
            self.assertEqual(await (await client.get(descriptor["url"])).read(), b"configured profile")
            status = await (await client.get("/api/simulator/status")).json()
            self.assertFalse(status["available"])
            self.assertEqual(status["error"], "Missing debug ELF")
            bundle.unlink()
            self.assertFalse((await (await client.get("/local-profile.json")).json())["available"])
            self.assertEqual((await client.get(descriptor["url"])).status, 404)
        finally:
            await client.close()

    async def test_websocket_origin_token_single_owner_and_cleanup(self):
        config, _ = self.fixture()
        client = TestClient(TestServer(application(config)))
        await client.start_server()
        try:
            r = await client.get(
                "/api/simulator/status", headers={"Origin": "https://example.com"}
            )
            self.assertEqual(r.status, 403)
            for port in (5173, 5174):
                self.assertEqual((await client.get("/api/simulator/status", headers={
                    "Origin": f"http://127.0.0.1:{port}",
                })).status, 200)
            info = await (await client.get("/api/simulator/status")).json()
            origin = str(client.make_url("/")).rstrip("/")
            with self.assertRaises(Exception):
                await client.ws_connect("/api/simulator/ws", headers={"Origin": origin})
            ws = await client.ws_connect(
                "/api/simulator/ws?token=" + info["token"], headers={"Origin": origin}
            )
            with self.assertRaises(Exception):
                await client.ws_connect(
                    "/api/simulator/ws?token=" + info["token"],
                    headers={"Origin": origin},
                )
            await ws.send_json({"requestId": 1, "command": "start"})
            m = await ws.receive_json()
            self.assertEqual(m["type"], "reset")
            disassembly = None
            while m["type"] != "stopped":
                m = await ws.receive_json()
                if m["type"] == "disassembly":
                    disassembly = m
            self.assertEqual(m["snapshot"]["reason"], "inference-entry")
            self.assertIsNotNone(disassembly)
            self.assertEqual(disassembly["generation"], m["generation"])
            self.assertEqual(len(disassembly["instructions"]), 5)
            await ws.close()
        finally:
            await client.close()


class ValidationTests(unittest.TestCase):
    def test_unsigned_never_accepts_shell_or_negative_values(self):
        for bad in [True, -1, "-1", "1;quit", "x14", str(2**64)]:
            with self.assertRaises(ValueError):
                unsigned(bad)
        self.assertEqual(unsigned("0xffffffffffffffff"), 2**64 - 1)
        self.assertEqual(unsigned(14), 14)

    def test_rechecks_artifacts_before_each_new_run(self):
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            config = object.__new__(Configuration)
            config.elf = Path(directory) / "program.elf"
            config.model = Path(directory) / "model.tflite"
            config.bundle = Path(directory) / "bundle.zip"
            for path in (config.elf, config.model, config.bundle):
                path.write_bytes(b"original")
            expected = hashlib.sha256(b"original").hexdigest()
            config.identity = {"elfHash": expected, "modelHash": expected}
            config.bundle_hash = expected
            config.verify_artifacts()
            for path in (config.elf, config.model, config.bundle):
                path.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "artifacts changed"):
                    config.verify_artifacts()
                path.write_bytes(b"original")

    def test_mismatched_artifacts(self):
        elf = (
            ROOT
            / "build/tflm-profile/rv64imc_rv64imc_release_with_logs_gcc/bin/efficientnet_lite0"
        )
        bundle = ROOT / "build/explorer/B0.zip"
        if not elf.exists() or not bundle.exists():
            self.skipTest("Local B0 not exported")
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "wrong.tflite"
            model.write_bytes(b"wrong model")
            with self.assertRaisesRegex(ValueError, "does not match"):
                Configuration(elf, model, bundle, SPIKE)


@unittest.skipUnless(
    os.environ.get("SPIKE_DEBUG_FULL_B0") == "1",
    "Set SPIKE_DEBUG_FULL_B0=1 for the full real inference acceptance",
)
class RealB0Tests(unittest.IsolatedAsyncioTestCase):
    async def test_full_inference_and_node4_loop(self):
        config = Configuration(
            ROOT
            / "build/tflm-profile/rv64imc_rv64imc_release_with_logs_gcc/bin/efficientnet_lite0",
            MODEL,
            ROOT / "build/explorer/B0.zip",
            SPIKE,
        )
        records = []

        async def emit(message):
            if message["type"] in {"stopped", "result", "reset"}:
                records.append(message)

        session = Session(config, emit)
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
            await command("stage", node=4)
            self.assertEqual(session.snapshot["node"], 4)
            self.assertEqual(int(session.snapshot["pc"]), config.stage_pcs[4])
            await command("breakpoint", key=1, pc=str(0x80005CAC))
            await command("continue")
            self.assertEqual(int(session.snapshot["pc"]), 0x80005CAC)
            self.assertEqual(
                int(session.snapshot["registers"][27])
                - int(session.snapshot["registers"][14]),
                15,
            )
            await command("step")
            self.assertEqual(int(session.snapshot["pc"]), 0x80005C94)
            pointer = int(session.snapshot["registers"][14])
            for _ in range(3):
                await command("step")
            self.assertEqual(int(session.snapshot["registers"][14]), pointer + 1)
            await command("breakpoint", key=1, remove=True)
            await command("continue")
            self.assertEqual(session.snapshot["reason"], "inference-complete")
            self.assertEqual(int(session.snapshot["retired"]) - begin, 4867278370)
            await command("continue")
            self.assertEqual(session.snapshot["reason"], "exited")
            self.assertTrue(records[-1]["passed"])
            self.assertEqual(records[-1]["checksum"], "0x4b6a91e2")
        finally:
            destination = ROOT / "build/simulator/B0/acceptance.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(records, indent=2) + "\n")
            await session.close()


if __name__ == "__main__":
    unittest.main()
