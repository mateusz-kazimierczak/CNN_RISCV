import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
import { simulationStages, firstNodeStage } from "./execution";
import { ModelGraph } from "../ModelGraph";
import { CodeView } from "../CodeView";
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
import { ABI, registerValue, type SimulationSession } from "./types";
import {
  buildProgramListing,
  programDecorations,
  instructionAddress,
  backendInstruction,
} from "./programListing";
import { DEFAULT_PANES, resizePanes } from "./layout";
import { WorkspaceHeader } from "../WorkspaceHeader";
import "./simulator.css";
export function Simulator({
  active = true,
  navigation,
  onStatusChange,
}: {
  active?: boolean;
  navigation?: ReactNode;
  onStatusChange?: (status: SimulationSession["status"]) => void;
}) {
  const {
    session,
    data,
    status,
    command: sendCommand,
    getText,
  } = useSimulation();
  useEffect(() => {
    onStatusChange?.(session.status);
  }, [session.status, onStatusChange]);
  const [destination, setDestination] = useState(4),
    [navPc, setNavPc] = useState(""),
    [navigationRequest, setNavigationRequest] = useState(0),
    [addressQuery, setAddressQuery] = useState(""),
    [addressError, setAddressError] = useState(""),
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
    [widths, setWidths] = useState<number[]>([...DEFAULT_PANES]),
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
  const stages = useMemo(() => (data ? simulationStages(data) : []), [data]);
  const activeStage =
    stages[
      running ? session.entered : (snapshot?.unitIndex ?? snapshot?.node ?? -1)
    ];
  const originIds = activeStage?.nodes || [];
  const activeNodeId = originIds.length === 1 ? originIds[0] : null;
  const activeNode = data?.graph.nodes.find((n) => n.id === activeNodeId);
  useEffect(() => {
    if (stages.length && !stages[destination]) setDestination(0);
  }, [stages, destination]);
  const stoppedPc = snapshot?.pc || "";
  const canEditBreakpoints =
    usable && ["ready", "paused", "exited"].includes(session.status);
  const [nativeInstructions, setNativeInstructions] = useState<Instruction[]>(
    [],
  );
  const program = useMemo(
    () =>
      buildProgramListing(
        data || { instructions: {}, functions: [] },
        nativeInstructions,
      ),
    [data, nativeInstructions],
  );
  const functionId = program.instructions[navPc]?.functionId || "";
  useEffect(() => {
    setNativeInstructions([]);
  }, [session.generation]);
  useEffect(() => {
    if (session.disassembly.length)
      setNativeInstructions(session.disassembly.map(backendInstruction));
  }, [session.disassembly]);
  useEffect(() => {
    if (!snapshot || data?.instructions[snapshot.pc] || !snapshot.instruction)
      return;
    const window = snapshot.instructionWindow || [
      { pc: snapshot.pc, ...snapshot.instruction },
    ];
    setNativeInstructions((previous) => {
      if (
        window.every((ins) =>
          previous.some((p) => p.pc === ins.pc && p.bits === ins.bits),
        )
      )
        return previous;
      const merged = new Map(previous.map((ins) => [ins.pc, ins]));
      for (const ins of window) merged.set(ins.pc, backendInstruction(ins));
      return [...merged.values()].slice(-128);
    });
  }, [snapshot, data]);

  const frameFor = (pc: string, index = 0): Frame | undefined =>
    data?.instructions[pc]?.frames[index];
  function browse(pc: string, follow = false) {
    setNavPc(pc);
    setNavigationRequest((request) => request + 1);
    setAddressError("");
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
  useEffect(() => {
    if (data && !snapshot && !navPc && program.firstPc)
      browse(program.firstPc, true);
  }, [data, snapshot, navPc, program.firstPc]);
  const assemblyFormatter = useMemo(
    () => createAssemblyFormatter(data?.functions || []),
    [data],
  );
  const decorations = useMemo(
    () =>
      programDecorations(
        program,
        stoppedPc,
        navPc,
        file,
        line,
        session.breakpoints,
        running ? "running" : session.status === "exited" ? "exited" : "paused",
      ),
    [
      program,
      stoppedPc,
      navPc,
      file,
      line,
      session.breakpoints,
      running,
      session.status,
    ],
  );
  const activeFrame = data?.instructions[navPc]?.frames[frameIndex];
  const inspected = instruction && program.instructions[instruction.pc];
  const selectedFunction = data?.functions.find((fn) => fn.id === functionId);
  const decodedSelection = Boolean(data?.instructions[navPc]);
  function jumpToAddress(e: React.FormEvent) {
    e.preventDefault();
    try {
      browse(instructionAddress(addressQuery, program));
    } catch (error) {
      setAddressError(error instanceof Error ? error.message : String(error));
    }
  }
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
        : { key: ++breakpointId.current, unit: destination },
    );
  }
  function changeFrame(index: number) {
    setFrameIndex(index);
    const frame = frameFor(navPc, index);
    setFile(frame?.file || "");
    setLine(frame?.line || 1);
  }
  useEffect(() => {
    if (!active) return;
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
  }, [active, paused, running, session.generation]);
  function resize(index: number, delta: number) {
    setWidths((values) => resizePanes(values, index, delta));
  }
  function drag(index: number, event: React.PointerEvent) {
    event.preventDefault();
    const start = event.clientX,
      initial = [...widths];
    const width = workspace.current!.getBoundingClientRect().width - 12;
    const move = (e: PointerEvent) =>
      setWidths(
        resizePanes(initial, index, ((e.clientX - start) / width) * 100),
      );
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  }
  const breakpointControls = (
    <div className="sim-break-controls">
      <button disabled={!canEditBreakpoints} onClick={toggleStage}>
        {session.breakpoints.some((b) => b.node === destination)
          ? "Remove stage breakpoint"
          : "Break on stage entry"}
      </button>
    </div>
  );
  return (
    <div className="simulator">
      <WorkspaceHeader navigation={navigation}>
        <span className={`sim-state ${running ? "is-running" : ""}`}>
          <i />
          {session.replaying ? "REPLAYING" : session.status.toUpperCase()}
        </span>
      </WorkspaceHeader>
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
            {stages.map((stage) => (
              <option key={stage.eventId} value={stage.index}>
                {stage.label}
              </option>
            ))}
          </select>
          <button
            disabled={!paused}
            onClick={() => {
              setFollowing(true);
              command("stage", { unit: destination });
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
              Destination: {stages[session.target]?.label || session.target}
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
          gridTemplateColumns: `minmax(0,${widths[0]}fr) 6px minmax(0,${widths[1]}fr) 6px minmax(0,${100 - widths[0] - widths[1]}fr)`,
        }}
      >
        <section
          className="sim-pane sim-assembly"
          aria-label="Assembly debugger"
        >
          <div className="sim-pane-heading">
            <span>
              <Cpu size={14} /> RISC-V assembly
            </span>
            <span className="sim-screenreader" role="status">
              {running
                ? "Simulation running; arrow marks the last stop"
                : paused && stoppedPc
                  ? `Paused before instruction ${hex(stoppedPc)}`
                  : session.status === "exited"
                    ? "Simulation exited"
                    : "Simulation ready"}
            </span>
            <button
              className={following ? "sim-follow active" : "sim-follow"}
              aria-label="Follow PC"
              aria-pressed={following}
              title="Return to the next instruction to execute without advancing Spike"
              disabled={!snapshot}
              onClick={() => snapshot && browse(snapshot.pc, true)}
            >
              <Crosshair size={13} />
              {following ? "Following PC" : "Follow PC"}
            </button>
          </div>
          <div className="sim-select-row">
            <select
              aria-label="Jump to function"
              value={functionId}
              onChange={(e) => {
                const f = data?.functions.find((f) => f.id === e.target.value);
                if (f) browse(f.pcs[0]);
              }}
            >
              <option value="">Jump to function…</option>
              {data?.functions.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </div>
          <form className="sim-address-jump" onSubmit={jumpToAddress}>
            <input
              aria-label="Jump to instruction address"
              placeholder="Address, e.g. 0x80005cac"
              value={addressQuery}
              onChange={(e) => {
                setAddressQuery(e.target.value);
                setAddressError("");
              }}
            />
            <button disabled={!program.count}>Go</button>
          </form>
          {addressError && (
            <div role="alert" className="sim-address-error">
              {addressError}
            </div>
          )}
          <div
            className="sim-listing-scope"
            title="All decoded executable code, including initialization and output checks. Listing order is memory address order, not execution order."
          >
            Full program ·{" "}
            {(program.count - nativeInstructions.length).toLocaleString()}{" "}
            instructions
            {nativeInstructions.length > 0 &&
              ` + ${nativeInstructions.length} native instructions`}
          </div>
          <div className="sim-code-caption">
            <span>
              ADDRESS{" "}
              <span className="sim-column-gap">INSTRUCTION / OPERANDS</span>
            </span>
            <span className="sim-gutter-key">
              <i className="sim-key-breakpoint" /> Breakpoint{" "}
              <i className="sim-key-pc" />{" "}
              {running ? "Last stop" : "Next instruction"}
            </span>
          </div>
          <div className="assembly-code sim-assembly-code">
            {program.count ? (
              <CodeView
                label="Simulator RISC-V assembly"
                autoFocus={active}
                text={program.text}
                language="riscv"
                line={program.pcToLine.get(navPc) || 1}
                revealRequest={navigationRequest}
                decorations={decorations}
                debugGutter={{
                  enabled: canEditBreakpoints,
                  instructionLines: program.breakableLines,
                }}
                addressTargets={program.targets}
                addressLines={program.pcToLine}
                onAddress={(pc) => browse(pc)}
                onLine={(n) => {
                  const pc = program.pcs[n - 1];
                  if (pc) browse(pc);
                }}
                onGutter={(n) => {
                  const pc = program.pcs[n - 1];
                  if (canEditBreakpoints && pc && data?.instructions[pc])
                    toggleAddress(pc);
                }}
                onRegister={(name, n, anchor) => {
                  const pc = program.pcs[n - 1];
                  if (!pc) return;
                  setInstruction(null);
                  setRegister({ register: name, pc, ...anchor });
                }}
                onInstruction={(n, anchor) => {
                  const pc = program.pcs[n - 1];
                  if (!pc) return;
                  setRegister(null);
                  setInstruction({ pc, ...anchor });
                }}
              />
            ) : (
              <div className="sim-placeholder">
                <Cpu size={30} />
                Loading full program disassembly…
                <small>F10 to step · F8 to continue / pause</small>
              </div>
            )}
          </div>
          <div className="sim-current-function" title={selectedFunction?.name}>
            {selectedFunction?.name ||
              (navPc && !data?.instructions[navPc]
                ? "Native code · outside ELF"
                : "Full executable")}
          </div>
          <div className="sim-assembly-footer">
            <span className="sim-live-dot" />
            <code>{stoppedPc ? hex(stoppedPc) : "—"}</code>
            <span>
              {activeStage
                ? activeStage.label
                : snapshot?.region || "Awaiting session"}
            </span>
            <button
              disabled={!canEditBreakpoints || !decodedSelection}
              aria-keyshortcuts="F9"
              title="Toggle address breakpoint (F9 when assembly has focus)"
              onClick={() => toggleAddress(navPc)}
            >
              {session.breakpoints.some((b) => b.pc === navPc && b.node < 0)
                ? "Remove breakpoint"
                : "Break at selection"}
            </button>
          </div>
        </section>
        <div
          role="separator"
          aria-label="Resize assembly and C++ panes"
          aria-valuenow={Math.round(widths[0])}
          aria-valuemin={32}
          aria-valuemax={Math.round(widths[0] + widths[1] - 20)}
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
        <section
          className="sim-pane sim-source"
          aria-label="C++ source context"
        >
          <div className="sim-pane-heading">
            <span>C++ implementation</span>
            <span className="sim-label">
              {!following
                ? "BROWSING SOURCE"
                : running
                  ? "LAST STOP MAPPING"
                  : "DWARF MAPPING"}
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
          aria-label="Resize C++ and model panes"
          aria-valuenow={Math.round(widths[1])}
          aria-valuemin={20}
          aria-valuemax={Math.round(100 - widths[0] - 14)}
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
        <section className="sim-pane sim-model" aria-label="Model context">
          <div className="sim-pane-heading">
            <span>
              <Layers size={14} /> Model
            </span>
            <span className="sim-label">
              {activeStage
                ? `${activeNode ? `NODE ${activeNode.index}` : `UNIT ${activeStage.unitId}`} ${running ? "ENTERED" : "ACTIVE"}`
                : running
                  ? "INITIALIZING"
                  : "NO ACTIVE UNIT"}
            </span>
          </div>
          <div className="sim-graph">
            {data ? (
              <ModelGraph
                active={active}
                data={data}
                selected={originIds[0] || null}
                selectedIds={originIds}
                onSelect={(id) => {
                  const stage = firstNodeStage(stages, id);
                  if (stage === null) {
                    const node = data.graph.nodes.find((n) => n.id === id);
                    setLocalError(
                      `Node ${node?.index ?? id} has no execution destination: ${node?.reason || "eliminated or unobserved"}`,
                    );
                  } else {
                    setLocalError("");
                    setDestination(stage);
                  }
                }}
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
            Click a node to select its first execution unit. Split units are
            listed separately above; shared units highlight all their origins.
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
                    {b.node >= 0
                      ? `${stages[b.node]?.label || `Unit ${b.node}`} entry`
                      : "Address"}{" "}
                    · <code>{hex(b.pc)}</code>
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
                  ? session.result.outputBytesValidated
                    ? `${session.result.outputBytesValidated.toLocaleString()} OUTPUT BYTES VERIFIED`
                    : "CHECKSUM VERIFIED"
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
      {active && register && data && (
        <RegisterInspector
          data={data}
          selection={register}
          onClose={() => setRegister(null)}
          live={
            snapshot && !running
              ? { pc: snapshot.pc, registers: snapshot.registers }
              : undefined
          }
          nodeId={activeNodeId}
          onDeclaration={(path, n) => {
            setFile(path);
            setLine(n);
            setFollowing(false);
            setRegister(null);
          }}
          onInstruction={(pc) => browse(pc)}
        />
      )}
      {active && instruction && inspected && (
        <InstructionInspector
          instruction={inspected}
          selection={instruction}
          onClose={() => setInstruction(null)}
          displayOperands={assemblyFormatter(inspected)}
          onTarget={
            inspected.transfer.target &&
            program.instructions[inspected.transfer.target]
              ? () => browse(inspected.transfer.target!)
              : undefined
          }
        />
      )}
      {active && sourceVariable && data && (
        <SourceVariableInspector
          data={data}
          selection={sourceVariable}
          nodeId={activeNodeId}
          live
          onClose={() => setSourceVariable(null)}
        />
      )}
    </div>
  );
}
