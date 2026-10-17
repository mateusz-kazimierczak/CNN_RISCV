import { useEffect, useMemo, useRef, useState } from "react";
import {
  Cpu,
  Play,
  Pause,
  SkipForward,
  RotateCcw,
  Crosshair,
  Terminal,
  Layers,
  MemoryStick,
  ChevronDown,
} from "lucide-react";
import { ModelGraph } from "../ModelGraph";
import { CodeView, type Decoration } from "../CodeView";
import {
  RegisterInspector,
  type RegisterSelection,
} from "../RegisterInspector";
import {
  InstructionInspector,
  type InstructionSelection,
} from "../InstructionInspector";
import {
  SourceVariableInspector,
  type SourceVariableSelection,
} from "../SourceVariableInspector";
import { createAssemblyFormatter } from "../assemblyDisplay";
import type { Frame, Instruction } from "../types";
import { hex, exact } from "../types";
import { useSimulation } from "./useSimulation";
import { ABI, registerValue } from "./types";
import "./simulator.css";
export function Simulator() {
  const {
    session,
    data,
    status,
    command: sendCommand,
    getText,
  } = useSimulation();
  const [destination, setDestination] = useState(4),
    [navPc, setNavPc] = useState(""),
    [functionId, setFunctionId] = useState(""),
    [following, setFollowing] = useState(true),
    [file, setFile] = useState(""),
    [line, setLine] = useState(1),
    [frameIndex, setFrameIndex] = useState(0),
    [source, setSource] = useState(""),
    [format, setFormat] = useState("hex"),
    [showRegisters, setShowRegisters] = useState(true),
    [register, setRegister] = useState<RegisterSelection | null>(null),
    [instruction, setInstruction] = useState<InstructionSelection | null>(null),
    [sourceVariable, setSourceVariable] =
      useState<SourceVariableSelection | null>(null),
    [widths, setWidths] = useState([20, 30]),
    [memoryAddress, setMemoryAddress] = useState("0x80000000"),
    [memorySize, setMemorySize] = useState("64"),
    [localError, setLocalError] = useState("");
  function command(op: string, args: Record<string, unknown> = {}) {
    if (["start", "restart", "step", "continue", "stage"].includes(op)) {
      setFollowing(true);
      setRegister(null);
      setInstruction(null);
      setSourceVariable(null);
    }
    sendCommand(op, args);
  }
  const workspace = useRef<HTMLDivElement>(null),
    breakpointId = useRef(1000);
  const snapshot = session.snapshot,
    running = session.status === "running",
    paused = session.status === "paused",
    usable = Boolean(data) && !status;
  const stoppedPc = snapshot?.pc || "";
  const frameFor = (pc: string, index = 0): Frame | undefined =>
    data?.instructions[pc]?.frames[index];
  function browse(pc: string, follow = false) {
    const ins = data?.instructions[pc];
    setNavPc(pc);
    if (ins?.functionId) setFunctionId(ins.functionId);
    else setFunctionId("");
    setFollowing(follow);
    setFrameIndex(0);
    const frame = frameFor(pc);
    setFile(frame?.file || "");
    setLine(frame?.line || 1);
    setRegister(null);
    setInstruction(null);
    setSourceVariable(null);
  }
  useEffect(() => {
    if (snapshot && following) browse(snapshot.pc, true);
  }, [snapshot, data]);
  useEffect(() => {
    if (session.generation) {
      setRegister(null);
      setInstruction(null);
      setFollowing(true);
      setNavPc("");
      setSource("");
    }
  }, [session.generation]);
  useEffect(() => {
    let cancelled = false;
    const path = data?.sources[file]?.archivePath;
    if (path)
      getText(path).then((text) => {
        if (!cancelled) setSource(text);
      });
    else setSource("");
    return () => {
      cancelled = true;
    };
  }, [file, data]);
  const fn = data?.functions.find((f) => f.id === functionId);
  const fallback: Instruction | undefined = snapshot?.instruction
    ? {
        pc: snapshot.pc,
        bits: snapshot.instruction.bits,
        length: snapshot.instruction.length,
        mnemonic: snapshot.instruction.text.trim().split(/\s+/)[0],
        operands: snapshot.instruction.text.trim().replace(/^\S+\s*/, ""),
        category: "other",
        functionId: null,
        functionIds: [],
        frames: [],
        transfer: { kind: "none", target: null },
      }
    : undefined;
  const pcs = fn?.pcs || (snapshot?.instruction ? [snapshot.pc] : []);
  const assemblyFormatter = useMemo(
    () => createAssemblyFormatter(data?.functions || []),
    [data],
  );
  const instructions = pcs
    .map((pc) => data?.instructions[pc] || fallback!)
    .filter(Boolean);
  const targets = new Map<number, string>();
  instructions.forEach((ins, i) => {
    if (ins.transfer.target && data?.instructions[ins.transfer.target])
      targets.set(i + 1, ins.transfer.target);
  });
  const decorations: Decoration[] = instructions.flatMap((ins, i) => {
    const result: Decoration[] = [];
    if (ins.pc === stoppedPc)
      result.push({ line: i + 1, className: "sim-live-line code-selected" });
    else if (ins.pc === navPc)
      result.push({ line: i + 1, className: "code-selected" });
    if (ins.frames.some((f) => f.file === file && f.line === line))
      result.push({ line: i + 1, className: "source-linked" });
    if (session.breakpoints.some((b) => b.pc === ins.pc))
      result.push({ line: i + 1, className: "sim-breakpoint" });
    return result;
  });
  const activeFrame = data?.instructions[navPc]?.frames[frameIndex];
  const inspected =
    instruction && (data?.instructions[instruction.pc] || fallback);
  const assembly = instructions
    .map(
      (ins) =>
        `${hex(ins.pc).padEnd(14)} ${ins.mnemonic.padEnd(9)} ${assemblyFormatter(ins)}`,
    )
    .join("\n");
  function toggleAddress(pc: string) {
    const existing = session.breakpoints.find((b) => b.pc === pc && b.node < 0);
    command(
      "breakpoint",
      existing
        ? { key: existing.key, remove: true }
        : { key: ++breakpointId.current, pc },
    );
  }
  function toggleStage() {
    const existing = session.breakpoints.find((b) => b.node === destination);
    command(
      "breakpoint",
      existing
        ? { key: existing.key, remove: true }
        : { key: ++breakpointId.current, node: destination },
    );
  }
  function changeFrame(index: number) {
    setFrameIndex(index);
    const frame = frameFor(navPc, index);
    setFile(frame?.file || "");
    setLine(frame?.line || 1);
  }
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "F10" && paused) {
        e.preventDefault();
        command("step");
      } else if (e.key === "F8") {
        e.preventDefault();
        if (running) command("pause");
        else if (paused) command("continue");
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [paused, running, session.generation]);
  function resize(index: number, delta: number) {
    setWidths((values) => {
      const copy = [...values];
      copy[index] = Math.min(
        index === 0 ? 35 : 50,
        Math.max(index === 0 ? 12 : 18, copy[index] + delta),
      );
      if (copy[0] + copy[1] > 75) copy[index] = 75 - copy[1 - index];
      return copy;
    });
  }
  function drag(index: number, event: React.PointerEvent) {
    const start = event.clientX,
      initial = [...widths],
      width = workspace.current!.getBoundingClientRect().width;
    const move = (e: PointerEvent) => {
      const change = ((e.clientX - start) / width) * 100;
      setWidths(() => {
        const next = [...initial];
        next[index] = Math.max(
          index === 0 ? 12 : 18,
          Math.min(index === 0 ? 35 : 50, initial[index] + change),
        );
        if (next[0] + next[1] > 75) next[index] = 75 - next[1 - index];
        return next;
      });
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  }
  const breakpointControls = (
    <div className="sim-break-controls">
      <button disabled={!paused} onClick={toggleStage}>
        {session.breakpoints.some((b) => b.node === destination)
          ? "Remove stage breakpoint"
          : "Break on stage entry"}
      </button>
    </div>
  );
  return (
    <div className="simulator">
      <header className="sim-header">
        <div className="sim-brand">
          <div className="sim-logo">
            <Cpu size={23} />
          </div>
          <div>
            <strong>
              Spike Studio <span>/</span>
            </strong>
            <small>LIVE RISC-V SIMULATION</small>
          </div>
        </div>
        <div className="sim-identity">
          EfficientNet-Lite0 <span>·</span> RV64IMC <span>·</span>{" "}
          {data?.provenance.configuration || "B0"}
        </div>
        <span className={`sim-state ${running ? "is-running" : ""}`}>
          <i />
          {session.replaying ? "REPLAYING" : session.status.toUpperCase()}
        </span>
      </header>
      <div className="sim-toolbar">
        <div className="sim-execution-controls">
          <button
            className="sim-primary"
            disabled={!usable || !["ready", "exited"].includes(session.status)}
            onClick={() => command("start")}
          >
            <Play size={14} />
            Start
          </button>
          <button
            disabled={!usable || running || session.status === "ready"}
            onClick={() => command("restart")}
            title="Restart the same deterministic input"
          >
            <RotateCcw size={14} />
            Restart
          </button>
          <span className="sim-rule" />
          <button
            disabled={!paused}
            onClick={() => command("step")}
            title="Execute one instruction (F10)"
          >
            <SkipForward size={15} />
            Step
          </button>
          <button
            disabled={!paused}
            onClick={() => command("continue")}
            title="Continue (F8)"
          >
            <Play size={14} />
            Continue
          </button>
          <button
            disabled={!running}
            onClick={() => command("pause")}
            title="Pause (F8)"
          >
            <Pause size={14} />
            Pause
          </button>
        </div>
        <div className="sim-stage-controls">
          <label htmlFor="destination">RUN TO</label>
          <select
            id="destination"
            aria-label="Destination stage"
            value={destination}
            disabled={!data || running}
            onChange={(e) => setDestination(Number(e.target.value))}
          >
            {data?.graph.nodes.map((n) => (
              <option key={n.id} value={n.index}>
                Node {n.index} · {n.group.replaceAll("_", " ")}
              </option>
            ))}
          </select>
          <button
            disabled={!paused}
            onClick={() => {
              setFollowing(true);
              command("stage", { node: destination });
            }}
          >
            <Layers size={14} />
            Run to stage
          </button>
        </div>
      </div>
      {(status || session.error || localError) && (
        <div role="alert" className="sim-alert">
          {status || session.error || localError}
        </div>
      )}
      <div className="sim-position">
        <div>
          <span className="sim-label">
            {running ? "LAST STOP" : "PAUSED AT"}
          </span>
          <code>{stoppedPc ? hex(stoppedPc) : "—"}</code>
          <span>
            {running
              ? "Running locally in Spike…"
              : snapshot?.reason.replaceAll("-", " ") ||
                "Start to initialize the model"}
          </span>
          {snapshot?.trap && (
            <strong>
              {snapshot.trap.name} at {hex(snapshot.trap.pc)}
            </strong>
          )}
        </div>
        <div>
          {session.target !== null && (
            <span className="sim-destination">
              Destination: node {session.target}
            </span>
          )}
          <span className="sim-label">LIVE RETIREMENTS</span>
          <strong>{exact(session.retired)}</strong>
        </div>
      </div>
      <div
        className="sim-workspace"
        ref={workspace}
        style={{
          gridTemplateColumns: `${widths[0]}% 5px ${widths[1]}% 5px minmax(0,1fr)`,
        }}
      >
        <section className="sim-pane sim-model">
          <div className="sim-pane-heading">
            <span>
              <Layers size={14} /> Model
            </span>
            <span className="sim-label">
              {running
                ? session.entered >= 0
                  ? `NODE ${session.entered} ENTERED`
                  : "INITIALIZING"
                : snapshot?.node !== undefined && snapshot.node >= 0
                  ? `NODE ${snapshot.node} ACTIVE`
                  : "NO ACTIVE OPERATOR"}
            </span>
          </div>
          <div className="sim-graph">
            {data ? (
              <ModelGraph
                data={data}
                selected={
                  running
                    ? session.entered >= 0
                      ? String(session.entered)
                      : null
                    : snapshot?.node !== undefined && snapshot.node >= 0
                      ? String(snapshot.node)
                      : null
                }
                onSelect={(id) => setDestination(Number(id))}
              />
            ) : (
              <div className="sim-placeholder">
                Loading configured evidence…
              </div>
            )}
          </div>
          <div className="sim-pane-note">
            Color and counts: recorded {data?.provenance.configuration || "B0"}{" "}
            profile.
            <br />
            Click a node to choose a run destination.
          </div>
        </section>
        <div
          role="separator"
          aria-label="Resize simulator model pane"
          aria-orientation="vertical"
          tabIndex={0}
          className="sim-resizer"
          onPointerDown={(e) => drag(0, e)}
          onKeyDown={(e) => {
            if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
              e.preventDefault();
              resize(0, e.key === "ArrowLeft" ? -2 : 2);
            }
          }}
        />
        <section className="sim-pane sim-source">
          <div className="sim-pane-heading">
            <span>C++ implementation</span>
            <span className="sim-label">
              {running ? "LAST STOP MAPPING" : "DWARF MAPPING"}
            </span>
          </div>
          <div className="sim-select-row">
            <select
              aria-label="Simulator source file"
              value={file}
              onChange={(e) => {
                setFile(e.target.value);
                setLine(1);
                setFollowing(false);
              }}
            >
              <option value="">Source unavailable</option>
              {data &&
                Object.keys(data.sources)
                  .sort()
                  .map((path) => (
                    <option key={path} value={path}>
                      {path.replace(".deps/tflite-micro/", "")}
                    </option>
                  ))}
            </select>
          </div>
          <div className="sim-code-caption">
            <span>{file.split("/").pop() || "No mapped source"}</span>
            <span>L{line}</span>
          </div>
          <div className="source-code sim-source-code">
            {source ? (
              <CodeView
                label="Simulator C++ source"
                text={source}
                line={line}
                decorations={[{ line, className: "code-selected" }]}
                onLine={(n) => {
                  setLine(n);
                  setFollowing(false);
                }}
                onSourceVariable={(name, n, anchor) => {
                  if (navPc)
                    setSourceVariable({
                      name,
                      pc: navPc,
                      file,
                      line: n,
                      ...anchor,
                    });
                }}
              />
            ) : (
              <div className="sim-placeholder">
                {file
                  ? "Source snapshot unavailable."
                  : "This address has no source mapping."}
                <small>Assembly and live state remain available.</small>
              </div>
            )}
          </div>
          <div className="sim-inline">
            <label>Inline frame</label>
            <select
              aria-label="Simulator inline frame"
              value={frameIndex}
              onChange={(e) => changeFrame(Number(e.target.value))}
            >
              {data?.instructions[navPc]?.frames.map((frame, i) => (
                <option key={i} value={i}>
                  {i === 0 ? "Innermost · " : ""}
                  {frame.function.split("(")[0]} {frame.file?.split("/").pop()}:
                  {frame.line}
                </option>
              ))}
            </select>
          </div>
        </section>
        <div
          role="separator"
          aria-label="Resize simulator source pane"
          aria-orientation="vertical"
          tabIndex={0}
          className="sim-resizer"
          onPointerDown={(e) => drag(1, e)}
          onKeyDown={(e) => {
            if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
              e.preventDefault();
              resize(1, e.key === "ArrowLeft" ? -2 : 2);
            }
          }}
        />
        <section className="sim-pane sim-assembly">
          <div className="sim-pane-heading">
            <span>
              <Cpu size={14} /> RISC-V assembly
            </span>
            <button
              className={following ? "sim-follow active" : "sim-follow"}
              disabled={!snapshot}
              onClick={() => snapshot && browse(snapshot.pc, true)}
            >
              <Crosshair size={13} />
              Follow PC
            </button>
          </div>
          <div className="sim-select-row">
            <select
              aria-label="Simulator function"
              value={functionId}
              onChange={(e) => {
                setFunctionId(e.target.value);
                const f = data?.functions.find((f) => f.id === e.target.value);
                if (f) browse(f.pcs[0]);
              }}
            >
              <option value="">Unmapped / startup code</option>
              {data?.functions.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </div>
          <div className="sim-code-caption">
            <span>
              ADDRESS{" "}
              <span className="sim-column-gap">INSTRUCTION / OPERANDS</span>
            </span>
            <span>Gutter: breakpoint</span>
          </div>
          <div className="assembly-code sim-assembly-code">
            {instructions.length ? (
              <CodeView
                label="Simulator RISC-V assembly"
                autoFocus
                text={assembly}
                language="riscv"
                line={Math.max(1, pcs.indexOf(navPc) + 1)}
                decorations={decorations}
                addressTargets={targets}
                onAddress={(pc) => browse(pc)}
                onLine={(n) => {
                  if (pcs[n - 1]) browse(pcs[n - 1]);
                }}
                onGutter={(n) => {
                  if (paused && pcs[n - 1]) toggleAddress(pcs[n - 1]);
                }}
                onRegister={(name, n, anchor) => {
                  setInstruction(null);
                  setRegister({ register: name, pc: pcs[n - 1], ...anchor });
                }}
                onInstruction={(n, anchor) => {
                  setRegister(null);
                  setInstruction({ pc: pcs[n - 1], ...anchor });
                }}
              />
            ) : (
              <div className="sim-placeholder">
                <Cpu size={30} />
                Start a simulation to inspect execution.
                <small>F10 to step · F8 to continue / pause</small>
              </div>
            )}
          </div>
          <div className="sim-assembly-footer">
            <span className="sim-live-dot" />
            <code>{stoppedPc ? hex(stoppedPc) : "—"}</code>
            <span>
              {snapshot?.node !== undefined && snapshot.node >= 0
                ? `Node ${snapshot.node}`
                : snapshot?.region || "Awaiting session"}
            </span>
            <button
              disabled={!paused || !navPc}
              onClick={() => toggleAddress(navPc)}
            >
              {session.breakpoints.some((b) => b.pc === navPc && b.node < 0)
                ? "Remove breakpoint"
                : "Break at selection"}
            </button>
          </div>
        </section>
      </div>
      <section className="sim-registers">
        <button
          className="sim-drawer-heading"
          aria-expanded={showRegisters}
          onClick={() => setShowRegisters(!showRegisters)}
        >
          <span>
            <Cpu size={15} />
            Integer registers{" "}
            <span className="sim-label">
              {running
                ? "LAST STOP · EXECUTION RUNNING"
                : "LIVE · BEFORE NEXT INSTRUCTION"}
            </span>
          </span>
          <ChevronDown size={15} />
        </button>
        {showRegisters && (
          <>
            <div className="sim-register-tools">
              <span>
                <i className="sim-changed-key" />
                Changed since previous stop
              </span>
              <select
                aria-label="Register format"
                value={format}
                onChange={(e) => setFormat(e.target.value)}
              >
                <option value="hex">Hexadecimal</option>
                <option value="signed">Signed decimal</option>
                <option value="unsigned">Unsigned decimal</option>
              </select>
            </div>
            <div className="sim-register-grid">
              {ABI.map((alias, i) => (
                <button
                  key={i}
                  disabled={!snapshot || running}
                  className={`sim-register ${snapshot && session.previous && snapshot.registers[i] !== session.previous.registers[i] ? "changed" : ""}`}
                  onClick={(event) => {
                    if (snapshot)
                      setRegister({
                        register: `x${i}`,
                        pc: snapshot.pc,
                        x: event.clientX,
                        y: event.clientY,
                      });
                  }}
                >
                  <span>
                    x{i}
                    <small>{alias}</small>
                  </span>
                  <code>
                    {snapshot
                      ? registerValue(snapshot.registers[i], format)
                      : "—"}
                  </code>
                </button>
              ))}
            </div>
          </>
        )}
      </section>
      <div className="sim-utilities">
        <details>
          <summary>
            <Layers size={14} />
            Breakpoints <span>{session.breakpoints.length}</span>
          </summary>
          <div className="sim-drawer-body">
            {breakpointControls}
            {session.breakpoints.length ? (
              session.breakpoints.map((b) => (
                <div key={b.key} className="sim-break-row">
                  <span>
                    {b.node >= 0 ? `Node ${b.node} entry` : "Address"} ·{" "}
                    <code>{hex(b.pc)}</code>
                  </span>
                  <button
                    disabled={!paused}
                    onClick={() =>
                      command("breakpoint", { key: b.key, remove: true })
                    }
                  >
                    Remove
                  </button>
                </div>
              ))
            ) : (
              <small>
                No breakpoints. Click the assembly gutter or break on a stage
                entry.
              </small>
            )}
          </div>
        </details>
        <details>
          <summary>
            <MemoryStick size={14} />
            Memory <span>READ ONLY</span>
          </summary>
          <div className="sim-drawer-body">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                try {
                  const address = BigInt(memoryAddress),
                    size = Number(memorySize);
                  if (
                    address < 0 ||
                    address > 2n ** 64n - 1n ||
                    !Number.isInteger(size) ||
                    size < 1 ||
                    size > 4096
                  )
                    throw new Error("Use a 64-bit address and 1–4096 bytes.");
                  setLocalError("");
                  command("memory", { address: address.toString(), size });
                } catch (error) {
                  setLocalError(String(error));
                }
              }}
            >
              <input
                aria-label="Memory address"
                value={memoryAddress}
                onChange={(e) => setMemoryAddress(e.target.value)}
              />
              <input
                aria-label="Memory byte count"
                value={memorySize}
                onChange={(e) => setMemorySize(e.target.value)}
              />
              <button disabled={!paused}>Read RAM</button>
            </form>
            {session.memory && (
              <pre>
                {Array.from(
                  { length: Math.ceil(session.memory.hex.length / 32) },
                  (_, i) =>
                    `${hex((BigInt(session.memory!.address) + BigInt(i * 16)).toString())}  ${session
                      .memory!.hex.slice(i * 32, i * 32 + 32)
                      .match(/../g)
                      ?.join(" ")}`,
                ).join("\n")}
              </pre>
            )}
          </div>
        </details>
        <details>
          <summary>
            <Terminal size={14} />
            Program output{" "}
            {session.result && (
              <span className={session.result.passed ? "sim-pass" : "sim-fail"}>
                {session.result.passed
                  ? "CHECKSUM VERIFIED"
                  : "VERIFICATION FAILED"}
              </span>
            )}
          </summary>
          <div className="sim-drawer-body">
            <pre aria-label="Simulator program output">
              {session.output || "Program output will appear here."}
            </pre>
            {session.result && (
              <small>
                Exit {session.result.exitCode} · checksum{" "}
                {session.result.checksum || "missing"} · expected{" "}
                {session.result.expected}
              </small>
            )}
          </div>
        </details>
      </div>
      <footer className="sim-footer">
        <span>
          <i className="sim-live-dot" />
          Live architectural state · single hart
        </span>
        <span>Source correspondence is best effort · retirements ≠ cycles</span>
      </footer>
      {register && data && (
        <RegisterInspector
          data={data}
          selection={register}
          onClose={() => setRegister(null)}
          live={
            snapshot && !running
              ? { pc: snapshot.pc, registers: snapshot.registers }
              : undefined
          }
          nodeId={
            snapshot?.node !== undefined && snapshot.node >= 0
              ? String(snapshot.node)
              : null
          }
          onDeclaration={(path, n) => {
            setFile(path);
            setLine(n);
            setFollowing(false);
            setRegister(null);
          }}
          onInstruction={(pc) => browse(pc)}
        />
      )}
      {instruction && inspected && (
        <InstructionInspector
          instruction={inspected}
          selection={instruction}
          onClose={() => setInstruction(null)}
          displayOperands={assemblyFormatter(inspected)}
          onTarget={
            inspected.transfer.target &&
            data?.instructions[inspected.transfer.target]
              ? () => browse(inspected.transfer.target!)
              : undefined
          }
        />
      )}
      {sourceVariable && data && (
        <SourceVariableInspector
          data={data}
          selection={sourceVariable}
          nodeId={
            snapshot?.node !== undefined && snapshot.node >= 0
              ? String(snapshot.node)
              : null
          }
          live
          onClose={() => setSourceVariable(null)}
        />
      )}
    </div>
  );
}
