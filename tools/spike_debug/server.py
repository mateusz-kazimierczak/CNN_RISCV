"""Loopback-only live Spike sessions. Run with python -m tools.spike_debug.server."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import secrets
import shutil
import socket
import tempfile
import zipfile
from pathlib import Path

from aiohttp import WSMsgType, web

from tools.profile_spike import MODEL, ROOT, Elf, symbols, unique_symbol

PROTOCOL = 1
MAX_U64 = 2**64 - 1


def unsigned(value, *, maximum=MAX_U64):
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, int))
        or not re.fullmatch(r"(?:0x[0-9a-fA-F]+|[0-9]+)", str(value))
    ):
        raise ValueError("Expected an unsigned integer")
    n = int(str(value), 16 if str(value).startswith("0x") else 10)
    if not 0 <= n <= maximum:
        raise ValueError("Integer out of range")
    return n


def graph_layout(elf: Path):
    from elftools.elf.elffile import ELFFile

    layouts = set()
    with elf.open("rb") as f:
        dwarf = ELFFile(f).get_dwarf_info()
        for cu in dwarf.iter_CUs():
            for die in cu.iter_DIEs():
                name = die.attributes.get("DW_AT_name")
                if (
                    die.tag not in {"DW_TAG_class_type", "DW_TAG_structure_type"}
                    or not name
                    or name.value != b"MicroInterpreterGraph"
                ):
                    continue
                members = {}
                for child in die.iter_children():
                    n = child.attributes.get("DW_AT_name")
                    offset = child.attributes.get("DW_AT_data_member_location")
                    if n and offset and isinstance(offset.value, int):
                        members[n.value.decode()] = offset.value
                if (
                    "current_operator_index_" in members
                    and "current_subgraph_index_" in members
                ):
                    layouts.add(
                        (
                            members["current_operator_index_"],
                            members["current_subgraph_index_"],
                        )
                    )
    if len(layouts) != 1:
        raise ValueError("Missing or ambiguous TFLM graph DWARF layout")
    return layouts.pop()


class Configuration:
    def __init__(
        self, elf: Path, model: Path, bundle: Path, spike: Path, configuration="B0"
    ):
        self.elf, self.model, self.bundle, self.spike = elf, model, bundle, spike
        for p in (elf, model, bundle, spike):
            if not p.is_file():
                raise ValueError(
                    f"Missing {p}. Supply the matching saved ELF, model and v2 bundle, and build the isolated debugger with gmake simulator-debug-build; no model or profile is built automatically."
                )
        from tools.spike_debug.evidence import execution_schedule, read_bundle

        self.evidence = read_bundle(bundle)
        provenance = self.evidence["provenance"]
        hashes = provenance["hashes"]
        if (
            hashlib.sha256(elf.read_bytes()).hexdigest() != hashes["profile_elf"]
            or hashlib.sha256(model.read_bytes()).hexdigest() != hashes["model"]
        ):
            raise ValueError("ELF/model does not match the evidence bundle")
        Elf(elf)
        self.instructions = self.evidence["instructions"]
        self.nodes = self.evidence["graph"]["nodes"]
        self.configuration = configuration
        syms = symbols(elf)
        self.adapter, invoke, allocate, self.stages = execution_schedule(
            self.evidence, elf, syms
        )
        self.stage_pcs = {s["index"]: s["entry"] for s in self.stages}
        lines = [f"region invoke {invoke:#x}"]
        if allocate is not None:
            lines.append(f"region allocate {allocate:#x}")
        if self.adapter == "compiler-v2":
            lines.append("execution compiler")
            lines.extend(
                f"unit {s['index']} {s['id']} {s['entry']:#x}" for s in self.stages
            )
        else:
            from tools.profile_spike import CALLBACKS

            index, subgraph = graph_layout(elf)
            if invoke != unique_symbol(
                syms, "tflite::MicroInterpreter::Invoke()"
            ) or allocate != unique_symbol(
                syms, "tflite::MicroInterpreter::AllocateTensors()"
            ):
                raise ValueError("LiteRT regions disagree with linked ELF")
            graph = unique_symbol(
                syms, "tflite::MicroInterpreterGraph::InvokeSubgraph(int)"
            )
            lines.append(f"graph {graph:#x} {index} {subgraph}")
            definitions = {}
            for stage in self.stages:
                if len(stage["nodes"]) != 1:
                    raise ValueError("LiteRT callback must identify one graph node")
                n = next(n for n in self.nodes if n["id"] == stage["nodes"][0])
                if n["index"] != stage["index"] or stage["entry"] != unique_symbol(
                    syms, CALLBACKS[n["type"]]
                ):
                    raise ValueError("LiteRT callback order/symbol differs from graph")
                definitions[n["type"]] = stage["entry"]
                lines.append(f"node {stage['index']} {n['type']}")
            lines.extend(f"operator {name} {pc:#x}" for name, pc in definitions.items())
        directory = ROOT / "build/simulator" / configuration
        directory.mkdir(parents=True, exist_ok=True)
        self.native_config = directory / "debug.cfg"
        self.native_config.write_text("\n".join(lines) + "\n")
        self.native_text = self.native_config.read_bytes()
        self.bundle_hash = hashlib.sha256(bundle.read_bytes()).hexdigest()
        self.identity = {
            "bundleHash": self.bundle_hash,
            "elfHash": hashes["profile_elf"],
            "modelHash": hashes["model"],
            "configuration": configuration,
            "isa": "rv64imc",
            "executionAdapter": self.adapter,
        }

    def verify_artifacts(self):
        for path, expected in (
            (self.elf, self.identity["elfHash"]),
            (self.model, self.identity["modelHash"]),
            (self.bundle, self.bundle_hash),
        ):
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                raise ValueError(
                    "Configured artifacts changed. Re-export matching evidence and restart the simulator backend before starting another run."
                )


class Native:
    def __init__(self, config: Configuration, generation: int, emit):
        self.config, self.generation, self.emit = config, generation, emit
        self.sequence = 0
        self.pending = {}
        self.process = None
        self.tasks = []
        self.output = ""
        self.closed = False

    async def launch(self):
        if hasattr(self.config, "verify_artifacts"):
            self.config.verify_artifacts()
        self.directory = tempfile.TemporaryDirectory(prefix="spike-studio-")
        private_elf = Path(self.directory.name) / "program.elf"
        private_config = Path(self.directory.name) / "debug.cfg"
        shutil.copyfile(self.config.elf, private_elf)
        if (
            self.config.identity.get("elfHash")
            and hashlib.sha256(private_elf.read_bytes()).hexdigest()
            != self.config.identity["elfHash"]
        ):
            raise ValueError(
                "Executable changed while starting the simulation; restart with matching artifacts."
            )
        private_config.write_bytes(
            self.config.native_text
            if hasattr(self.config, "native_text")
            else self.config.native_config.read_bytes()
        )
        parent, child = socket.socketpair()
        parent.setblocking(False)
        child.set_inheritable(True)
        self.reader, self.writer = await asyncio.open_connection(
            sock=parent, limit=262144
        )
        loop = asyncio.get_running_loop()
        self.ready = loop.create_future()
        try:
            self.process = await asyncio.create_subprocess_exec(
                str(self.config.spike),
                f"--isa={getattr(self.config, 'isa', 'rv64imc')}",
                "-m128",
                f"--host-debug-fd={child.fileno()}",
                f"--host-debug-config={private_config}",
                str(private_elf),
                pass_fds=(child.fileno(),),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        finally:
            child.close()
        self.tasks = [
            asyncio.create_task(self.read()),
            asyncio.create_task(self.console(self.process.stdout)),
            asyncio.create_task(self.console(self.process.stderr)),
        ]
        return await asyncio.wait_for(self.ready, 15)

    async def console(self, stream):
        while data := await stream.read(4096):
            text = data.decode(errors="replace")
            self.output = (self.output + text)[-262144:]
            await self.emit(
                {"type": "output", "generation": self.generation, "text": text}
            )

    async def read(self):
        try:
            while line := await self.reader.readline():
                message = json.loads(line)
                if message.get("protocol") != PROTOCOL:
                    raise ValueError("Native protocol mismatch")
                if message["type"] == "progress":
                    await self.emit({**message, "generation": self.generation})
                    continue
                if message["id"] == 0 and not self.ready.done():
                    self.ready.set_result(message)
                    continue
                future = self.pending.pop(message["id"], None)
                if future and not future.done():
                    if message["type"] == "error":
                        future.set_exception(ValueError(message["error"]))
                    else:
                        future.set_result(message)
            raise ConnectionError("Simulator exited or closed its control channel")
        except (Exception, asyncio.CancelledError) as e:  # noqa: BLE001 - settle every pending IPC request on channel failure
            if not self.ready.done():
                self.ready.set_exception(e)
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError(str(e)))
            self.pending.clear()
            if not self.closed:
                await self.emit(
                    {
                        "type": "native-closed",
                        "generation": self.generation,
                        "error": str(e),
                    }
                )

    async def command(self, op, *args):
        if self.closed:
            raise ValueError("Session is closed")
        self.sequence += 1
        request = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[request] = future
        self.writer.write((" ".join(map(str, (request, op, *args))) + "\n").encode())
        await self.writer.drain()
        return await future

    async def close(self):
        self.closed = True
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if hasattr(self, "writer"):
            self.writer.close()
            await self.writer.wait_closed()
        if hasattr(self, "directory"):
            self.directory.cleanup()


class Session:
    def __init__(self, config, emit):
        self.config, self.emit = config, emit
        self.native = None
        self.generation = 0
        self.snapshot = None
        self.breakpoints = {}
        self.target = None
        self.busy = False

    async def send(self, message):
        if hasattr(self.config, "stages"):
            message = dict(message)
            if "snapshot" in message:
                snapshot = dict(message["snapshot"])
                at = snapshot["node"]
                unit = (
                    self.config.stages[at]
                    if 0 <= at < len(self.config.stages)
                    else None
                )
                snapshot.update(
                    unitIndex=at,
                    unitId=unit["id"] if unit else None,
                    nodeIds=unit["nodes"] if unit else [],
                )
                snapshot["node"] = next(
                    (
                        n["index"]
                        for n in self.config.nodes
                        if unit
                        and len(unit["nodes"]) == 1
                        and n["id"] == unit["nodes"][0]
                    ),
                    -1,
                )
                entered = snapshot["entered"]
                previous = (
                    self.config.stages[entered]
                    if 0 <= entered < len(self.config.stages)
                    else None
                )
                snapshot.update(
                    enteredUnitId=previous["id"] if previous else None,
                    enteredNodeIds=previous["nodes"] if previous else [],
                )
                message["snapshot"] = snapshot
        await self.emit(
            {**message, "generation": self.generation, "target": self.target}
        )

    async def stop(self, message, request):
        self.snapshot = message["snapshot"]
        self.busy = False
        if self.snapshot["reason"] == "stage-breakpoint" or (
            self.target is not None
            and self.snapshot["node"] == self.target
            and int(self.snapshot["pc"]) == self.config.stage_pcs[self.target]
        ):
            self.target = None
            await self.native.command("target", -1)
        await self.send(
            {"type": "stopped", "requestId": request, "snapshot": self.snapshot}
        )
        if self.snapshot["reason"] == "exited":
            await self.native.process.wait()
            await asyncio.gather(*self.native.tasks[1:], return_exceptions=True)
            match = re.search(r"output_fnv1a=(0x[0-9a-f]+)", self.native.output)
            expected = self.config.evidence["provenance"]["output_fnv1a"]
            expected_sha = self.config.evidence["provenance"].get("output_sha256")
            output = re.search(
                r"^output_hex=([0-9a-f]+)$", self.native.output, re.MULTILINE
            )
            payload = (
                bytes.fromhex(output[1]) if output and len(output[1]) % 2 == 0 else b""
            )
            exact = bool(
                expected_sha
                and len(payload) == 1000
                and hashlib.sha256(payload).hexdigest() == expected_sha
            )
            await self.send(
                {
                    "type": "result",
                    "exitCode": self.native.process.returncode,
                    "checksum": match[1] if match else None,
                    "expected": expected,
                    "outputBytesValidated": len(payload) if exact else None,
                    "passed": self.native.process.returncode == 0
                    and bool(match)
                    and match[1] == expected
                    and (exact if expected_sha else True)
                    and self.snapshot.get("inferenceComplete", False)
                    and not self.snapshot.get("error"),
                }
            )

    async def launch(self, request):
        if self.native:
            await self.native.close()
        self.generation += 1
        self.snapshot = None
        await self.send(
            {
                "type": "reset",
                "requestId": request,
                "replaying": self.target is not None,
            }
        )
        self.native = Native(self.config, self.generation, self.emit)
        ready = await self.native.launch()
        if ready["snapshot"].get("instructionWindow"):
            await self.send(
                {
                    "type": "disassembly",
                    "instructions": ready["snapshot"]["instructionWindow"],
                }
            )
        for key, b in self.breakpoints.items():
            await self.native.command("break", key, int(b["pc"]), b.get("node", -1))
        if self.target is not None:
            await self.native.command("target", self.target)
        return await self.native.command("run")

    async def advance(self, operation):
        if self.target is not None:
            await self.native.command("target", self.target)
        result = await self.native.command(operation)
        while (
            operation == "run"
            and self.target is not None
            and result["snapshot"]["reason"] == "inference-entry"
            and not any(
                b["pc"] == result["snapshot"]["pc"] and b["node"] < 0
                for b in self.breakpoints.values()
            )
        ):
            result = await self.native.command("run")
        return result

    async def execute(self, message):
        request = unsigned(message.get("requestId"))
        op = message.get("command")
        if op == "pause":
            if self.busy and self.native:
                await self.native.command("pause")
            return
        if self.busy:
            raise ValueError("Simulation is running; pause first")
        if (
            op not in {"start", "restart"}
            and message.get("generation") != self.generation
        ):
            raise ValueError("Stale session generation")
        self.busy = True
        try:
            if op in {"start", "restart"}:
                self.target = None
                result = await self.launch(request)
                await self.stop(result, request)
            elif op == "breakpoint":
                key = unsigned(message.get("key"), maximum=2**31 - 1)
                if message.get("remove"):
                    self.breakpoints.pop(key, None)
                    if (
                        self.native
                        and self.native.process
                        and self.native.process.returncode is None
                    ):
                        await self.native.command("delete", key)
                else:
                    if len(self.breakpoints) >= 256 and key not in self.breakpoints:
                        raise ValueError("Maximum 256 breakpoints")
                    node = message.get("unit", message.get("node", -1))
                    if node != -1:
                        node = unsigned(
                            node,
                            maximum=len(
                                getattr(self.config, "stages", self.config.nodes)
                            )
                            - 1,
                        )
                        pc = self.config.stage_pcs[node]
                    else:
                        pc = unsigned(message.get("pc"))
                    if str(pc) not in self.config.instructions:
                        raise ValueError(
                            "Breakpoint address is not a decoded instruction"
                        )
                    if (
                        self.native
                        and self.native.process
                        and self.native.process.returncode is None
                    ):
                        await self.native.command("break", key, pc, node)
                    self.breakpoints[key] = {"key": key, "pc": str(pc), "node": node}
                await self.send(
                    {
                        "type": "breakpoints",
                        "requestId": request,
                        "breakpoints": list(self.breakpoints.values()),
                    }
                )
            elif not self.native:
                raise ValueError("Start the simulation first")
            elif op in {"step", "continue"}:
                await self.send({"type": "running", "requestId": request})
                result = await self.advance("step" if op == "step" else "run")
                await self.stop(result, request)
            elif op == "stage":
                node = unsigned(
                    message.get("unit", message.get("node")),
                    maximum=len(getattr(self.config, "stages", self.config.nodes)) - 1,
                )
                self.target = node
                if (
                    self.snapshot
                    and self.snapshot["node"] == node
                    and int(self.snapshot["pc"]) == self.config.stage_pcs[node]
                ):
                    self.target = None
                    await self.stop({"snapshot": self.snapshot}, request)
                    return
                await self.send({"type": "running", "requestId": request})
                if self.snapshot and self.snapshot["entered"] >= node:
                    result = await self.launch(request)
                    # During replay, honor user breakpoints reached before Invoke.
                    if result["snapshot"]["reason"] != "inference-entry" or any(
                        b["pc"] == result["snapshot"]["pc"] and b["node"] < 0
                        for b in self.breakpoints.values()
                    ):
                        await self.stop(result, request)
                        return
                await self.stop(await self.advance("run"), request)
            elif op == "memory":
                address = unsigned(message.get("address"))
                size = unsigned(message.get("size"), maximum=4096)
                if not size:
                    raise ValueError("Memory size must be 1..4096 bytes")
                await self.send(
                    {
                        **await self.native.command("memory", address, size),
                        "requestId": request,
                    }
                )
            else:
                raise ValueError("Unknown simulation command")
        finally:
            self.busy = False

    async def close(self):
        if self.native:
            await self.native.close()


def application(
    config: Configuration | None,
    error="",
    dist: Path | None = None,
    local_bundle: Path | None = None,
    configuration="B0",
):
    app = web.Application(client_max_size=65536)
    local_bundle = getattr(config, "bundle", local_bundle)
    configuration = getattr(config, "configuration", configuration)
    token = secrets.token_urlsafe(32)
    owner = None
    session = None
    tasks = set()

    @web.middleware
    async def security(request, handler):
        expected = {
            f"http://127.0.0.1:{request.url.port}",
            f"http://localhost:{request.url.port}",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        }
        if request.headers.get("Host", "").split(":")[0] not in {
            "127.0.0.1",
            "localhost",
        }:
            raise web.HTTPForbidden(text="Loopback host required")
        origin = request.headers.get("Origin")
        if origin and origin not in expected:
            raise web.HTTPForbidden(text="Unexpected origin")
        if request.path.endswith("/ws") and (
            not origin or request.query.get("token") != token
        ):
            raise web.HTTPForbidden(text="Session token and local origin required")
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.middlewares.append(security)

    async def status(request):
        return web.json_response(
            {
                "protocol": PROTOCOL,
                "available": bool(config),
                "error": error,
                "token": token,
                "identity": config.identity if config else None,
            }
        )

    async def evidence(request):
        if not config:
            raise web.HTTPServiceUnavailable(text=error)
        try:
            config.verify_artifacts()
        except ValueError as e:
            raise web.HTTPConflict(text=str(e))
        return web.FileResponse(config.bundle)

    async def websocket(request):
        nonlocal owner, session
        if not config:
            raise web.HTTPServiceUnavailable(text=error)
        if owner is not None:
            raise web.HTTPConflict(text="One simulation session is already active")
        ws = web.WebSocketResponse(max_msg_size=65536, heartbeat=20)
        owner = ws
        try:
            await ws.prepare(request)
        except BaseException:
            owner = None
            raise

        async def emit(message):
            if not ws.closed:
                await ws.send_json(message)

        session = Session(config, emit)

        async def handle(data):
            try:
                await session.execute(data)
            except Exception as e:  # noqa: BLE001 - report command failures at the websocket boundary
                await emit(
                    {
                        "type": "error",
                        "requestId": data.get("requestId"),
                        "generation": session.generation,
                        "running": session.busy,
                        "error": str(e),
                    }
                )

        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(message.data)
                        if not isinstance(data, dict):
                            raise TypeError("Expected an object")
                        # A running command owns native execution; only Pause may
                        # run concurrently to interrupt it through private IPC.
                        if session.busy and data.get("command") != "pause":
                            raise ValueError("Simulation is running; pause first")
                        task = asyncio.create_task(handle(data))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
                    except Exception as e:  # noqa: BLE001 - reject malformed client messages without losing the session  # noqa: BLE001 - report command failures at the websocket boundary
                        await emit(
                            {
                                "type": "error",
                                "error": str(e),
                                "generation": session.generation,
                                "running": session.busy,
                            }
                        )
        finally:
            await session.close()
            for task in list(tasks):
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            owner = None
            session = None
        return ws

    async def local_profile(request):
        return web.json_response(
            {
                "available": bool(local_bundle and local_bundle.is_file()),
                "configuration": configuration,
                "url": "/profiles/local.zip",
            }
        )

    async def profile_bundle(request):
        if not local_bundle or not local_bundle.is_file():
            raise web.HTTPNotFound(
                text="Export the selected build's matching v2 bundle first"
            )
        return web.FileResponse(local_bundle)

    app.router.add_get("/local-profile.json", local_profile)
    app.router.add_get("/profiles/local.zip", profile_bundle)
    app.router.add_get("/api/simulator/status", status)
    app.router.add_get("/api/simulator/evidence", evidence)
    app.router.add_get("/api/simulator/ws", websocket)
    if dist and dist.is_dir():

        async def index(request):
            return web.FileResponse(dist / "index.html")

        app.router.add_get("/", index)
        app.router.add_static("/", dist, show_index=False)

    async def shutdown(app):
        if owner:
            await owner.close()
        if session:
            await session.close()

    app.on_shutdown.append(shutdown)
    return app


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--configuration", default="B0")
    p.add_argument("--port", type=int, default=8765)
    source = p.add_mutually_exclusive_group()
    source.add_argument(
        "--build-manifest",
        type=Path,
        help="Use the immutable ELF from a verified compiler build snapshot",
    )
    source.add_argument(
        "--elf",
        type=Path,
    )
    p.add_argument("--model", type=Path, default=MODEL)
    p.add_argument("--bundle", type=Path)
    p.add_argument("--spike", type=Path, default=ROOT / ".deps/spike-debug/bin/spike")
    a = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.configuration):
        p.error("Invalid configuration")
    try:
        if a.build_manifest:
            from compiler.build_evidence import local_file, open_build

            snapshot, build = open_build(a.build_manifest)
            if build["build"]["kind"] != "rv64":
                raise ValueError("Live simulation requires a target RV64 build")
            a.elf = local_file(
                snapshot.parent, build["files"][build["build"]["binary"]]["blob"]
            )
        elif a.elf is None:
            a.elf = (
                ROOT
                / "build/tflm-profile/rv64imc_rv64imc_release_with_logs_gcc/bin/efficientnet_lite0"
            )
        config = Configuration(
            a.elf,
            a.model,
            a.bundle or ROOT / f"build/explorer/{a.configuration}.zip",
            a.spike,
            a.configuration,
        )
        error = ""
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as e:
        config = None
        error = str(e)
        print(error)
    print(f"Execution Atlas (Explorer + Simulator): http://127.0.0.1:{a.port}/")
    web.run_app(
        application(
            config,
            error,
            ROOT / "explorer/dist",
            a.bundle or ROOT / f"build/explorer/{a.configuration}.zip",
            a.configuration,
        ),
        host="127.0.0.1",
        port=a.port,
    )


if __name__ == "__main__":
    main()
