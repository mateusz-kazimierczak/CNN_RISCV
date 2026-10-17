import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Cpu,
  FileArchive,
  GitBranch,
  Layers3,
  LoaderCircle,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import type { Evidence, Event, Func, Loop, Counts } from "./types";
import { compact, count, exact, hex, percent, sum } from "./types";
import { ModelGraph } from "./ModelGraph";
import { CodeView, type Decoration } from "./CodeView";
import { Advanced, type CompilerFocus } from "./Advanced";
import { LIMITS } from "./bundle";
import { matchingSourcePcs } from "./sourceMapping";
import { createAssemblyFormatter } from "./assemblyDisplay";
import { RegisterInspector, type RegisterSelection } from "./RegisterInspector";
import {
  InstructionInspector,
  type InstructionSelection,
} from "./InstructionInspector";
import {
  SourceVariableInspector,
  type SourceVariableSelection,
} from "./SourceVariableInspector";
import { CompilationInspector } from "./CompilationInspector";
import { nodeScope, selectionScopes } from "./scopes";
import { WorkspaceHeader } from "./WorkspaceHeader";
interface Nav {
  eventId: string;
  functionId: string;
  pc: string;
  sourcePath: string;
  line: number;
  frameIndex: number;
  loopId: string;
}
const emptyNav: Nav = {
  eventId: "",
  functionId: "",
  pc: "",
  sourcePath: "",
  line: 1,
  frameIndex: 0,
  loopId: "",
};
function initialNav(data: Evidence, event: Event): Nav {
  const scores = new Map<string, bigint>();
  for (const [pc, n] of Object.entries(event.counts)) {
    const f = data.instructions[pc].functionId;
    if (f) scores.set(f, (scores.get(f) || 0n) + BigInt(n));
  }
  const id =
    [...scores].sort((a, b) =>
      a[1] > b[1] ? -1 : a[1] < b[1] ? 1 : 0,
    )[0]?.[0] ||
    data.functions[0]?.id ||
    "";
  const fn = data.functions.find((f) => f.id === id);
  const pc =
    [...(fn?.pcs || [])].sort((a, b) =>
      count(event.counts, a) > count(event.counts, b)
        ? -1
        : count(event.counts, a) < count(event.counts, b)
          ? 1
          : 0,
    )[0] || "";
  const frame = data.instructions[pc]?.frames[0];
  return {
    ...emptyNav,
    eventId: event.id,
    functionId: id,
    pc,
    sourcePath: frame?.file || "",
    line: frame?.line || 1,
  };
}
const shortFunction = (name: string) =>
  name
    .replace("tflite::reference_integer_ops::", "")
    .replace("tflite::", "")
    .replace("(anonymous namespace)::", "")
    .replace(/\(.*$/, "");
function Mix({
  counts,
  data,
  pcs,
}: {
  counts: Counts;
  data: Evidence;
  pcs: string[];
}) {
  const mix: Record<string, bigint> = {};
  for (const pc of pcs) {
    const category = data.instructions[pc].category;
    mix[category] = (mix[category] || 0n) + count(counts, pc);
  }
  const total = sum(pcs, counts);
  return (
    <div className="mix">
      <div className="mix-bar">
        {Object.entries(mix)
          .filter(([, n]) => n > 0n)
          .map(([c, n]) => (
            <span
              className={"mix-segment " + c}
              key={c}
              style={{ width: percent(n, total) }}
              title={`${c}: ${exact(n)} (${percent(n, total)})`}
            />
          ))}
      </div>
      <div className="mix-legend">
        {Object.entries(mix)
          .filter(([, n]) => n > 0n)
          .sort((a, b) => (a[1] > b[1] ? -1 : 1))
          .map(([c, n]) => (
            <span key={c}>
              <i className={c} />
              {c.replaceAll("_", " ")} <b>{percent(n, total)}</b>
            </span>
          ))}
      </div>
    </div>
  );
}
export function App({
  active = true,
  navigation,
}: {
  active?: boolean;
  navigation?: ReactNode;
}) {
  const [data, setData] = useState<Evidence | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [local, setLocal] = useState<{
      available: boolean;
      configuration: string;
      url: string;
    } | null>(null);
  const [inspection, setInspection] = useState<
    | ({ kind: "register" } & RegisterSelection)
    | ({ kind: "instruction" } & InstructionSelection)
    | ({ kind: "source" } & SourceVariableSelection)
    | null
  >(null);
  const [compilerFocus, setCompilerFocus] = useState<CompilerFocus | null>(
    null,
  );
  const compilerPanel = useRef<HTMLElement>(null);
  const [history, setHistory] = useState<Nav[]>([emptyNav]),
    [historyIndex, setHistoryIndex] = useState(0);
  const nav = history[historyIndex];
  const [functionQuery, setFunctionQuery] = useState(""),
    [frameText, setFrameText] = useState(""),
    [sourceError, setSourceError] = useState(""),
    [advanced, setAdvanced] = useState(false),
    [assemblyAnalysis, setAssemblyAnalysis] = useState(false),
    [details, setDetails] = useState(false),
    [dragging, setDragging] = useState(false),
    [operatorTab, setOperatorTab] = useState("loops");
  const analysisBody = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (advanced && compilerFocus)
      compilerPanel.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
  }, [compilerFocus, advanced]);
  useEffect(() => {
    setCompilerFocus(null);
  }, [nav.functionId]);
  useEffect(() => {
    analysisBody.current?.scrollTo({ top: 0 });
  }, [nav.loopId, nav.eventId, operatorTab, assemblyAnalysis]);
  const [widths, setWidths] = useState([27, 34]);
  const workspace = useRef<HTMLDivElement>(null),
    fileInput = useRef<HTMLInputElement>(null);
  const worker = useRef<Worker | null>(null),
    sequence = useRef(0),
    pending = useRef(
      new Map<
        number,
        { resolve: (value: unknown) => void; reject: (e: Error) => void }
      >(),
    ),
    textCache = useRef(new Map<string, string>());
  const request = useCallback(
    <T,>(
      message: Record<string, unknown>,
      transfer: Transferable[] = [],
      target?: Worker,
    ): Promise<T> =>
      new Promise((resolve, reject) => {
        const id = ++sequence.current;
        pending.current.set(id, {
          resolve: resolve as (v: unknown) => void,
          reject,
        });
        (target || worker.current)!.postMessage({ ...message, id }, transfer);
      }),
    [],
  );
  const getText = useCallback(
    async (path: string) => {
      if (textCache.current.has(path)) return textCache.current.get(path)!;
      const result = await request<{ text: string }>({ type: "text", path });
      textCache.current.set(path, result.text);
      return result.text;
    },
    [request],
  );
  useEffect(() => {
    fetch("./local-profile.json")
      .then((r) => (r.ok ? r.json() : null))
      .then(setLocal)
      .catch(() => {});
    return () => {
      worker.current?.terminate();
      for (const p of pending.current.values())
        p.reject(new Error("Viewer closed"));
      pending.current.clear();
    };
  }, []);
  const load = async (file: File | Response) => {
    setBusy(true);
    setError("");
    let candidate: Worker | null = null;
    try {
      if (file instanceof File && file.size > LIMITS.compressed)
        throw new Error("ZIP exceeds 256 MiB compressed limit");
      const bytes = await file.arrayBuffer();
      if (bytes.byteLength > LIMITS.compressed)
        throw new Error("ZIP exceeds 256 MiB compressed limit");
      const w = new Worker(new URL("./bundle.worker.ts", import.meta.url), {
        type: "module",
      });
      candidate = w;
      w.onmessage = ({ data: message }) => {
        const p = pending.current.get(message.id);
        if (!p) return;
        pending.current.delete(message.id);
        if (message.type === "error") p.reject(new Error(message.error));
        else p.resolve(message);
      };
      w.onerror = () => {
        for (const p of pending.current.values())
          p.reject(new Error("Bundle worker failed"));
        pending.current.clear();
      };
      const result = await request<{ evidence: Evidence }>(
        { type: "load", bytes },
        [bytes],
        w,
      );
      const evidence = result.evidence;
      worker.current?.terminate();
      worker.current = w;
      candidate = null;
      for (const p of pending.current.values())
        p.reject(new Error("Bundle replaced"));
      pending.current.clear();
      textCache.current.clear();
      const hottest = [
        ...evidence.events.filter((e) => e.scope === "execution-unit"),
      ].sort((a, b) => (BigInt(a.total) > BigInt(b.total) ? -1 : 1))[0];
      setData(evidence);
      setHistory([initialNav(evidence, hottest || evidence.events[0])]);
      setHistoryIndex(0);
      setFunctionQuery("");
      setAdvanced(false);
      setCompilerFocus(null);
      setAssemblyAnalysis(false);
      setInspection(null);
    } catch (e) {
      candidate?.terminate();
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const loadLocal = async () => {
    try {
      setError("");
      const response = await fetch(local!.url);
      if (!response.ok)
        throw new Error(
          "Local profile asset is unavailable. Run gmake explorer-export.",
        );
      await load(response);
    } catch (e) {
      setError(String(e));
    }
  };
  const navigate = (patch: Partial<Nav>) => {
    setInspection(null);
    const next = { ...nav, ...patch };
    if (JSON.stringify(next) === JSON.stringify(nav)) return;
    setHistory([...history.slice(0, historyIndex + 1), next]);
    setHistoryIndex(historyIndex + 1);
  };
  const scopes = useMemo(() => (data ? selectionScopes(data) : []), [data]);
  const event = scopes.find((e) => e.id === nav.eventId),
    fn = data?.functions.find((f) => f.id === nav.functionId) || null;
  const selectedNode = data?.graph.nodes.find((n) => n.id === event?.nodeId);
  const counts = event?.counts || {};
  const selectEvent = (id: string) => {
    const e = scopes.find((e) => e.id === id)!;
    navigate(initialNav(data!, e));
  };
  const selectPc = (
    pc: string,
    patch: Partial<Nav> = {},
    originPc?: string,
  ) => {
    const atPc = (address: string, base: Nav): Nav | null => {
      const i = data?.instructions[address];
      if (!i) return null;
      const frameIndex = Math.min(
        base.frameIndex,
        Math.max(i.frames.length - 1, 0),
      );
      const f = i.frames[frameIndex];
      return {
        ...base,
        pc: address,
        frameIndex,
        functionId: i.functionIds.includes(base.functionId)
          ? base.functionId
          : i.functionId || base.functionId,
        sourcePath: f?.file || "",
        line: f?.line || 1,
        loopId: i.functionIds.includes(base.functionId) ? base.loopId : "",
      };
    };
    const origin = originPc && originPc !== nav.pc ? atPc(originPc, nav) : null;
    const destination = atPc(pc, origin || nav);
    if (!destination) return;
    if (origin) {
      // Remember the clicked branch/call even if the user scrolled to it
      // without selecting its row first. Commit both entries atomically.
      const entries = [...history.slice(0, historyIndex + 1), origin];
      const next = { ...destination, ...patch };
      if (JSON.stringify(next) !== JSON.stringify(origin)) entries.push(next);
      setInspection(null);
      setHistory(entries);
      setHistoryIndex(entries.length - 1);
    } else navigate({ ...destination, ...patch });
  };
  const selectFunction = (id: string) => {
    const f = data!.functions.find((f) => f.id === id)!;
    const pc = [...f.pcs].sort((a, b) =>
      count(counts, a) > count(counts, b)
        ? -1
        : count(counts, a) < count(counts, b)
          ? 1
          : 0,
    )[0];
    selectPc(pc, { functionId: id, loopId: "" });
  };
  const loop = fn?.cfg.loops.find((l) => l.id === nav.loopId);
  const loops = useMemo(() => {
    if (!data || !event) return [];
    return data.functions
      .flatMap((f) =>
        f.cfg.loops.map((l) => ({
          fn: f,
          loop: l,
          total: sum(l.pcs, event.counts),
        })),
      )
      .filter((l) => l.total > 0n)
      .sort((a, b) => (a.total > b.total ? -1 : a.total < b.total ? 1 : 0));
  }, [data, event]);
  const selectLoop = (l: Loop, f: Func) => {
    const pc = [...l.pcs].sort((a, b) =>
      count(counts, a) > count(counts, b)
        ? -1
        : count(counts, a) < count(counts, b)
          ? 1
          : 0,
    )[0];
    selectPc(pc, { functionId: f.id, loopId: l.id });
  };
  const functionTotals = useMemo(() => {
    const totals = new Map<string, bigint>();
    if (data && event)
      for (const [pc, n] of Object.entries(event.counts)) {
        const id = data.instructions[pc].functionId;
        if (id) totals.set(id, (totals.get(id) || 0n) + BigInt(n));
      }
    return totals;
  }, [data, event]);
  const functions = useMemo(
    () =>
      data
        ? [...data.functions]
            .filter(
              (f) =>
                !functionQuery ||
                `${f.name} ${f.address} ${hex(f.address)}`
                  .toLowerCase()
                  .includes(functionQuery.toLowerCase()),
            )
            .sort((a, b) =>
              (functionTotals.get(a.id) || 0n) >
              (functionTotals.get(b.id) || 0n)
                ? -1
                : (functionTotals.get(a.id) || 0n) <
                    (functionTotals.get(b.id) || 0n)
                  ? 1
                  : a.name.localeCompare(b.name),
            )
        : [],
    [data, functionQuery, functionTotals],
  );
  const source = data?.sources[nav.sourcePath];
  useEffect(() => {
    let cancelled = false;
    setSourceError("");
    setFrameText("");
    if (!source?.archivePath) {
      setSourceError(
        "Source text is unavailable for this location. Assembly and counts remain available.",
      );
      return;
    }
    getText(source.archivePath)
      .then((text) => {
        if (!cancelled) setFrameText(text);
      })
      .catch((e) => {
        if (!cancelled) setSourceError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [source, getText]);
  const linePcs = useMemo(() => {
    const lines = new Map<number, string[]>();
    if (data)
      for (const [pc, i] of Object.entries(data.instructions)) {
        const f = i.frames[nav.frameIndex];
        if (f?.file === nav.sourcePath && f.line)
          lines.set(f.line, [...(lines.get(f.line) || []), pc]);
      }
    return lines;
  }, [data, nav.sourcePath, nav.frameIndex]);
  const lineCounts = useMemo(
    () => new Map([...linePcs].map(([line, pcs]) => [line, sum(pcs, counts)])),
    [linePcs, counts],
  );
  const sourceDecorations = useMemo(() => {
    const max = [...lineCounts.values()].reduce((m, v) => (v > m ? v : m), 1n);
    const result: Decoration[] = [...lineCounts]
      .filter(([, n]) => n > 0n)
      .map(([line, n]) => ({
        line,
        className: `heat-${Math.min(4, Number((n * 4n) / max))}`,
      }));
    result.push({
      line: nav.line,
      className: "code-selected",
    });
    return result;
  }, [lineCounts, nav.line, nav.frameIndex]);
  const formatAssemblyOperands = useMemo(
    () => createAssemblyFormatter(data?.functions || []),
    [data],
  );
  const assemblyTargets = useMemo(() => {
    const targets = new Map<number, string>();
    if (fn && data)
      fn.pcs.forEach((pc, index) => {
        const target = data.instructions[pc].transfer.target;
        if (target && data.instructions[target]) targets.set(index + 1, target);
      });
    return targets;
  }, [fn, data]);
  const assemblyText = useMemo(
    () =>
      fn && data
        ? fn.pcs
            .map((pc) => {
              const i = data.instructions[pc];
              return `${hex(pc)}  ${exact(count(counts, pc)).padStart(14)}  ${i.mnemonic.padEnd(9)} ${formatAssemblyOperands(i)}`;
            })
            .join("\n")
        : "",
    [fn, data, counts, formatAssemblyOperands],
  );
  const selectedSourcePcs = useMemo(
    () =>
      new Set(
        data
          ? matchingSourcePcs(data.instructions, nav.sourcePath, nav.line)
          : [],
      ),
    [data, nav.sourcePath, nav.line],
  );
  const matchingAssemblyPcs =
    fn?.pcs.filter((pc) => selectedSourcePcs.has(pc)) || [];
  const loopPcs = new Set(loop?.pcs || []);
  const assemblyDecorations: Decoration[] =
    fn?.pcs.flatMap((pc, index) => {
      const result: Decoration[] = [];
      if (loopPcs.has(pc))
        result.push({ line: index + 1, className: "loop-highlight" });
      if (selectedSourcePcs.has(pc))
        result.push({
          line: index + 1,
          className: "source-linked",
        });
      if (pc === nav.pc)
        result.push({
          line: index + 1,
          className: "code-selected",
        });
      return result;
    }) || [];
  const instruction = data?.instructions[nav.pc];
  const block = fn?.cfg.blocks.find((b) => b.pcs.includes(nav.pc));
  const annotations =
    data?.annotations.filter(
      (a) =>
        a.status === "reviewed" &&
        a.pcs.some((pc) => (loop ? loopPcs.has(pc) : pc === nav.pc)),
    ) || [];
  const startResize = (index: number, e: React.PointerEvent) => {
    e.preventDefault();
    const rect = workspace.current!.getBoundingClientRect();
    const original = [...widths];
    const move = (ev: PointerEvent) => {
      const pos = ((ev.clientX - rect.left) / rect.width) * 100;
      setWidths(
        index === 0
          ? [
              Math.max(18, Math.min(pos, 45)),
              original[1] + original[0] - Math.max(18, Math.min(pos, 45)),
            ]
          : [
              original[0],
              Math.max(22, Math.min(pos - original[0], 80 - original[0])),
            ],
      );
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  };
  const frames = instruction?.frames || [];
  return (
    <div
      className={"app " + (dragging ? "dragging" : "")}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node))
          setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (e.dataTransfer.files[0]) void load(e.dataTransfer.files[0]);
      }}
    >
      <WorkspaceHeader navigation={navigation}>
        <div className="topbar-actions">
          {data && (
            <span className="chip green">
              <span className="status-dot" /> {data.provenance.configuration} ·
              validated capture
            </span>
          )}
          {data && (
            <button
              className={"evidence-button " + (details ? "active" : "")}
              onClick={() => setDetails(!details)}
              aria-expanded={details}
            >
              <ShieldCheck size={15} /> Evidence <ChevronDown size={13} />
            </button>
          )}
          {local?.available && (
            <button
              disabled={busy}
              className="button subtle"
              onClick={() => void loadLocal()}
            >
              <FileArchive size={14} /> Load local {local.configuration}
            </button>
          )}
          <button
            className="button"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
          >
            <Upload size={14} /> Open bundle
          </button>
          <input
            aria-label="Open profile bundle"
            ref={fileInput}
            type="file"
            accept=".zip"
            hidden
            onChange={(e) => {
              if (e.target.files?.[0]) void load(e.target.files[0]);
              e.target.value = "";
            }}
          />
        </div>
      </WorkspaceHeader>
      {error && (
        <div
          role="alert"
          aria-label="Bundle import error"
          className="error-banner"
        >
          <span>{error}</span>
          <button aria-label="Dismiss error" onClick={() => setError("")}>
            <X size={16} />
          </button>
        </div>
      )}
      {busy && (
        <div className="loading">
          <LoaderCircle size={16} className="spin" /> Validating bundle
          integrity and indexing execution evidence…
        </div>
      )}
      {!data ? (
        <main className="welcome">
          <div className="welcome-label">
            <span className="status-dot" /> LOCAL EXECUTION EVIDENCE
          </div>
          <h1>
            Follow the computation.
            <br />
            <em>Find the instructions.</em>
          </h1>
          <p>
            Explore how a neural-network operator becomes machine work.
            <br />
            Trace measured hotspots through C++, control flow, and RISC-V
            assembly.
          </p>
          <div className="welcome-actions">
            {local?.available && (
              <button
                className="button primary"
                disabled={busy}
                onClick={() => void loadLocal()}
              >
                Explore {local.configuration}{" "}
                {local.configuration === "B0" ? "baseline" : "build"}{" "}
                <ArrowRight size={16} />
              </button>
            )}
            <button
              className="button"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
            >
              <Upload size={15} /> Open a profile bundle
            </button>
          </div>
          <div className="welcome-flow">
            {[
              [
                Layers3,
                "01",
                "Model graph",
                "Find expensive operators and follow tensor dependencies.",
              ],
              [
                BookOpen,
                "02",
                "C++ implementation",
                "Connect measured work to kernels and inline source.",
              ],
              [
                Cpu,
                "03",
                "Machine instructions",
                "Inspect hot loops, instruction mix, and compiler evidence.",
              ],
            ].map(([Icon, n, title, description]) => {
              const I = Icon as typeof Cpu;
              return (
                <div className="welcome-step" key={String(n)}>
                  <span>{String(n)}</span>
                  <I size={24} />
                  <h3>{String(title)}</h3>
                  <p>{String(description)}</p>
                </div>
              );
            })}
          </div>
          <div className="welcome-foot">
            <ShieldCheck size={14} /> Browser-only analysis · Files stay on this
            device · No cycle estimates
          </div>
        </main>
      ) : (
        <>
          {details && (
            <section className="provenance">
              <div>
                <b>Measured executable</b>
                <code>{data.provenance.hashes.profile_elf}</code>
                <span>{data.provenance.compiler}</span>
              </div>
              <div>
                <b>Measurement boundaries</b>
                <span>{data.provenance.boundaries}</span>
                <span>
                  Sources: {data.provenance.sourceSnapshotStatus}.
                  Missing/ambiguous mappings remain visible.
                </span>
              </div>
              <div>
                <b>Integrity and coverage</b>
                <span>
                  {data.capabilities.sourceMappedInstructions.toLocaleString()}{" "}
                  / {data.capabilities.staticInstructions.toLocaleString()}{" "}
                  static instructions mapped
                </span>
                <span>
                  {data.compilerUnits.length} compiler units · seed{" "}
                  {data.provenance.input_seed} · output{" "}
                  {data.provenance.output_fnv1a}
                </span>
              </div>
            </section>
          )}
          <div className="selection-bar">
            <div className="history">
              <button
                title="Previous selection"
                aria-label="Previous selection"
                disabled={historyIndex === 0}
                onClick={() => {
                  setInspection(null);
                  setHistoryIndex(historyIndex - 1);
                }}
              >
                <ArrowLeft size={16} />
              </button>
              <button
                title="Next selection"
                aria-label="Next selection"
                disabled={historyIndex === history.length - 1}
                onClick={() => {
                  setInspection(null);
                  setHistoryIndex(historyIndex + 1);
                }}
              >
                <ArrowRight size={16} />
              </button>
            </div>
            <select
              aria-label="Execution scope"
              value={nav.eventId}
              onChange={(e) => selectEvent(e.target.value)}
            >
              <optgroup label="Regions">
                {data.events
                  .filter((e) => e.scope !== "execution-unit")
                  .map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name === "invoke"
                        ? "Whole inference"
                        : e.name === "allocate"
                          ? "AllocateTensors (separate setup)"
                          : e.name}
                    </option>
                  ))}
              </optgroup>
              <optgroup label="Execution units">
                {data.executionPlan.units.flatMap((u) =>
                  u.eventIds.map((id) => (
                    <option key={id} value={id}>
                      {u.id} · {u.symbol}
                    </option>
                  )),
                )}
              </optgroup>
              <optgroup label="Logical graph nodes">
                {data.graph.nodes.map((n) => (
                  <option key={n.id} value={nodeScope(data, n).id}>
                    Node {n.index} · {n.group}
                  </option>
                ))}
              </optgroup>
            </select>
            <ChevronRight size={14} />
            <span className="selection-name">
              {selectedNode
                ? `${selectedNode.type.replaceAll("_", " ")} · ${selectedNode.output_shapes[0]?.join(" × ")}`
                : event?.name}
            </span>
            {event?.shared && (
              <span className="chip">
                Shared measurement · full unit cost, not apportioned
              </span>
            )}
            {event?.evidence === "unavailable" && (
              <span className="chip">
                {selectedNode?.reason || "No observed execution"}
              </span>
            )}
            <div className="scope-count">
              <strong>
                {event?.evidence === "unavailable"
                  ? "Unavailable"
                  : exact(event?.total || "0")}
              </strong>{" "}
              instruction retirements{" "}
              <span className="chip">
                {event?.evidence} ·{" "}
                {event?.evidence === "unavailable"
                  ? "no observed measurement"
                  : event?.name === "allocate"
                    ? "separate setup region"
                    : `${percent(BigInt(event?.total || 0), BigInt(data.totals.inference))} of inference`}
              </span>
            </div>
          </div>
          <main
            className="workspace"
            ref={workspace}
            style={{
              gridTemplateColumns: `minmax(0,${widths[0]}fr) 5px minmax(0,${widths[1]}fr) 5px minmax(0,${100 - widths[0] - widths[1]}fr)`,
            }}
          >
            <section className="pane model-pane">
              <div className="pane-title">
                <span>
                  <Layers3 size={15} /> Model graph
                </span>
                <span className="pane-tag">
                  {data.graph.nodes.length} NODES
                </span>
              </div>
              <div className="graph-wrap">
                <ModelGraph
                  active={active}
                  data={data}
                  selected={event?.nodeId || null}
                  onSelect={(id) =>
                    selectEvent(
                      nodeScope(
                        data,
                        data.graph.nodes.find((n) => n.id === id)!,
                      ).id,
                    )
                  }
                />
                <div className="graph-key">
                  <span /> instruction contribution{" "}
                  <span className="key-gradient" />
                </div>
              </div>
            </section>
            <div
              className="resize-handle"
              role="separator"
              aria-label="Resize model pane"
              aria-orientation="vertical"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft" || e.key === "ArrowRight")
                  setWidths([
                    Math.max(
                      18,
                      Math.min(
                        40,
                        widths[0] + (e.key === "ArrowRight" ? 2 : -2),
                      ),
                    ),
                    widths[1],
                  ]);
              }}
              onPointerDown={(e) => startResize(0, e)}
            />
            <section className="pane source-pane">
              <div className="pane-title">
                <span>
                  <BookOpen size={15} /> C++ implementation
                </span>
                <span className="pane-tag">DWARF MAPPING</span>
              </div>
              <div className="source-tools">
                <select
                  aria-label="Source file"
                  title={nav.sourcePath}
                  value={nav.sourcePath}
                  onChange={(e) =>
                    navigate({ sourcePath: e.target.value, line: 1 })
                  }
                >
                  <option value="">Source unavailable</option>
                  {Object.keys(data.sources).map((path) => (
                    <option key={path} value={path}>
                      {path.replace(".deps/tflite-micro/", "")}
                    </option>
                  ))}
                </select>
                <span className="line-indicator">L{nav.line}</span>
              </div>
              <div className="source-context">
                <span className="source-dot" />{" "}
                {nav.sourcePath.split("/").pop() || "No source location"}{" "}
                <span>
                  {frames.length > 1
                    ? `${frames.length} inline frames`
                    : "Best-effort correspondence"}
                </span>
              </div>
              <div className="source-code">
                {sourceError ? (
                  <div className="empty-inline">{sourceError}</div>
                ) : (
                  <CodeView
                    text={frameText}
                    line={nav.line}
                    decorations={sourceDecorations}
                    label="C++ source"
                    onSourceVariable={(name, line, anchor) =>
                      setInspection({
                        kind: "source",
                        name,
                        file: nav.sourcePath,
                        line,
                        pc: nav.pc,
                        ...anchor,
                      })
                    }
                    onLine={(line) => {
                      const all = matchingSourcePcs(
                        data.instructions,
                        nav.sourcePath,
                        line,
                      );
                      const inFunction = all.filter((pc) =>
                        data.instructions[pc].functionIds.includes(
                          nav.functionId,
                        ),
                      );
                      const pc = [
                        ...(inFunction.length ? inFunction : all),
                      ].sort((a, b) =>
                        count(counts, a) > count(counts, b)
                          ? -1
                          : count(counts, a) < count(counts, b)
                            ? 1
                            : 0,
                      )[0];
                      if (pc)
                        selectPc(pc, {
                          sourcePath: nav.sourcePath,
                          line,
                          frameIndex: nav.frameIndex,
                        });
                      else navigate({ line, pc: "" });
                    }}
                  />
                )}
              </div>
              <div className="source-footer">
                <div>
                  <span className="heat-scale" /> instruction retirements
                  attributed to line
                </div>
                <strong>{exact(lineCounts.get(nav.line) || 0n)}</strong>
                <small>
                  Counts are not line executions. Each instruction contributes
                  once at the selected inline depth.
                </small>
              </div>
              <div className="source-frames">
                <label>
                  Inline frame{" "}
                  <select
                    aria-label="Inline frame"
                    value={Math.min(
                      nav.frameIndex,
                      Math.max(frames.length - 1, 0),
                    )}
                    onChange={(e) => {
                      const index = Number(e.target.value),
                        f = frames[index];
                      navigate({
                        frameIndex: index,
                        sourcePath: f?.file || "",
                        line: f?.line || 1,
                      });
                    }}
                  >
                    {frames.length ? (
                      frames.map((f, i) => (
                        <option key={i} value={i}>
                          {i === 0 ? "Innermost" : `Caller ${i}`} ·{" "}
                          {shortFunction(f.function)} {f.file?.split("/").pop()}
                          :{f.line || "?"}
                        </option>
                      ))
                    ) : (
                      <option value={0}>No DWARF frames</option>
                    )}
                  </select>
                </label>
              </div>
            </section>
            <div
              className="resize-handle"
              role="separator"
              aria-label="Resize source pane"
              aria-orientation="vertical"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft" || e.key === "ArrowRight")
                  setWidths([
                    widths[0],
                    Math.max(
                      22,
                      Math.min(
                        48,
                        widths[1] + (e.key === "ArrowRight" ? 2 : -2),
                      ),
                    ),
                  ]);
              }}
              onPointerDown={(e) => startResize(1, e)}
            />
            <section className="pane assembly-pane">
              <div className="pane-title">
                <span>
                  <Cpu size={15} /> RISC-V assembly
                </span>
                <span
                  className={
                    "pane-tag" +
                    (matchingAssemblyPcs.length ? " source-match-count" : "")
                  }
                  title={`${matchingAssemblyPcs.length} instructions in this function correspond to ${nav.sourcePath}:${nav.line}`}
                  data-testid="source-match-count"
                >
                  {matchingAssemblyPcs.length
                    ? `${matchingAssemblyPcs.length} SOURCE MATCHES`
                    : "EXACT PC COUNTS"}
                </span>
              </div>
              <div className="assembly-tools">
                <input
                  aria-label="Search functions"
                  placeholder="Filter functions / addresses…"
                  value={functionQuery}
                  onChange={(e) => setFunctionQuery(e.target.value)}
                />
                <select
                  aria-label="Function"
                  title={fn?.name}
                  value={nav.functionId}
                  onChange={(e) => selectFunction(e.target.value)}
                >
                  {fn && !functions.some((f) => f.id === fn.id) && (
                    <option value={fn.id}>{fn.name}</option>
                  )}
                  {functions.map((f) => (
                    <option key={f.id} value={f.id}>
                      {compact(functionTotals.get(f.id) || 0n)} · {f.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="assembly-columns">
                <span>ADDRESS</span>
                <span>RETIREMENTS</span>
                <span>INSTRUCTION / OPERANDS</span>
              </div>
              <div className="assembly-code">
                <CodeView
                  text={assemblyText}
                  language="riscv"
                  line={fn ? fn.pcs.indexOf(nav.pc) + 1 : 1}
                  decorations={assemblyDecorations}
                  label="RISC-V assembly"
                  addressTargets={assemblyTargets}
                  onAddress={(pc, line) => selectPc(pc, {}, fn?.pcs[line - 1])}
                  onRegister={(register, line, anchor) => {
                    const pc = fn?.pcs[line - 1];
                    if (pc)
                      setInspection({
                        kind: "register",
                        register,
                        pc,
                        ...anchor,
                      });
                  }}
                  onInstruction={(line, anchor) => {
                    const pc = fn?.pcs[line - 1];
                    if (pc)
                      setInspection({ kind: "instruction", pc, ...anchor });
                  }}
                  onLine={(line) => {
                    const pc = fn?.pcs[line - 1];
                    if (pc) selectPc(pc);
                  }}
                />
              </div>
              <div
                className="instruction-detail"
                data-testid="instruction-detail"
              >
                <code>
                  {nav.pc ? hex(nav.pc) : "—"} <b>{instruction?.mnemonic}</b>
                </code>
                <span>{exact(count(counts, nav.pc))} retired</span>
                {instruction?.transfer.target && (
                  <button
                    title="Navigate to static target"
                    onClick={() => selectPc(instruction.transfer.target!)}
                    disabled={!data.instructions[instruction.transfer.target]}
                  >
                    <ArrowUpRight size={12} />
                    {hex(instruction.transfer.target)}
                  </button>
                )}
              </div>
            </section>
          </main>
          <section className="advanced assembly-analysis">
            <button
              className="advanced-toggle"
              onClick={() => setAssemblyAnalysis(!assemblyAnalysis)}
              aria-expanded={assemblyAnalysis}
              aria-controls="assembly-analysis-content"
            >
              {assemblyAnalysis ? (
                <ChevronDown size={15} />
              ) : (
                <ChevronRight size={15} />
              )}
              <Activity size={15} />
              <strong>Assembly Analysis</strong>
              <span>Hot loops · instruction mix · tensors</span>
            </button>
            {assemblyAnalysis && (
              <div
                id="assembly-analysis-content"
                className="assembly-analysis-content"
              >
                <div className="block-bar">
                  <GitBranch size={13} />
                  <select
                    aria-label="Basic block"
                    value={block?.id || ""}
                    onChange={(e) =>
                      selectPc(
                        fn!.cfg.blocks.find((b) => b.id === e.target.value)!
                          .start,
                      )
                    }
                  >
                    {fn?.cfg.blocks.map((b) => (
                      <option key={b.id} value={b.id}>
                        Block {hex(b.start)} · {b.pcs.length} instructions
                      </option>
                    ))}
                  </select>
                  {block?.successors.map((e, i) => (
                    <button
                      key={i}
                      title={`Static ${e.kind} edge; frequency unknown`}
                      onClick={() =>
                        selectPc(
                          fn!.cfg.blocks.find((b) => b.id === e.to)!.start,
                        )
                      }
                    >
                      <ArrowRight size={11} />
                      {hex(fn!.cfg.blocks.find((b) => b.id === e.to)!.start)}
                    </button>
                  ))}
                </div>
                <div className="analysis-tabs">
                  <button
                    className={operatorTab === "loops" ? "active" : ""}
                    onClick={() => setOperatorTab("loops")}
                  >
                    <Activity size={13} /> Hot loops <span>{loops.length}</span>
                  </button>
                  <button
                    className={operatorTab === "mix" ? "active" : ""}
                    onClick={() => setOperatorTab("mix")}
                  >
                    Instruction mix
                  </button>
                  <button
                    className={operatorTab === "metadata" ? "active" : ""}
                    onClick={() => setOperatorTab("metadata")}
                  >
                    Tensors
                  </button>
                </div>
                <div className="analysis-body" ref={analysisBody}>
                  {operatorTab === "loops" ? (
                    <>
                      {loop ? (
                        <>
                          <div className="loop-selected-header">
                            <div>
                              <span className="eyebrow">
                                SELECTED{" "}
                                {loop.kind === "natural"
                                  ? "NATURAL LOOP"
                                  : "CYCLIC REGION"}
                              </span>
                              <h3>
                                {hex(loop.pcs[0])}{" "}
                                <span>{loop.pcs.length} instructions</span>
                              </h3>
                            </div>
                            <button
                              title="Clear loop highlight"
                              onClick={() => navigate({ loopId: "" })}
                            >
                              <X size={14} />
                            </button>
                          </div>
                          <div className="loop-stats">
                            <div>
                              <strong>{compact(sum(loop.pcs, counts))}</strong>
                              <span>inclusive body</span>
                            </div>
                            <div>
                              <strong>
                                {compact(sum(loop.exclusivePcs, counts))}
                              </strong>
                              <span>excluding child bodies</span>
                            </div>
                            <div>
                              <strong>
                                {percent(
                                  sum(loop.pcs, counts),
                                  BigInt(event!.total),
                                )}
                              </strong>
                              <span>of selected scope</span>
                            </div>
                          </div>
                          <Mix counts={counts} data={data} pcs={loop.pcs} />
                          <div className="loop-relations">
                            {loop.parent && (
                              <button
                                onClick={() =>
                                  selectLoop(
                                    fn!.cfg.loops.find(
                                      (l) => l.id === loop.parent,
                                    )!,
                                    fn!,
                                  )
                                }
                              >
                                ↑ Parent loop
                              </button>
                            )}
                            {loop.children.map((id) => (
                              <button
                                key={id}
                                onClick={() =>
                                  selectLoop(
                                    fn!.cfg.loops.find((l) => l.id === id)!,
                                    fn!,
                                  )
                                }
                              >
                                ↓{" "}
                                {
                                  fn!.cfg.loops.find((l) => l.id === id)!.pcs
                                    .length
                                }
                                -instruction child
                              </button>
                            ))}
                          </div>
                          {annotations.map((a) => (
                            <div className="annotation" key={a.id}>
                              <span
                                className={"annotation-category " + a.category}
                              />
                              <div>
                                <b>{a.title}</b>
                                <p>{a.description}</p>
                                <div className="annotation-pcs">
                                  {a.pcs
                                    .filter((pc) => loopPcs.has(pc))
                                    .map((pc) => (
                                      <button
                                        key={pc}
                                        onClick={() => selectPc(pc)}
                                      >
                                        {hex(pc)}
                                      </button>
                                    ))}
                                </div>
                              </div>
                            </div>
                          ))}
                          <div className="analysis-caveat">
                            Static body counts exclude out-of-line callees.
                            Nested inclusive totals overlap.{" "}
                            {loop.confidence === "partial-cfg"
                              ? "Control-flow graph has unresolved transfers; loop boundaries may be incomplete."
                              : "Loop detected from resolved static control flow."}
                          </div>
                        </>
                      ) : (
                        <div className="analysis-caption">
                          Loops ranked by retirements in the selected scope.
                          Expand an outer loop to inspect its nested reduction
                          loops.
                        </div>
                      )}
                      <div className="loop-list">
                        {loops.map(({ fn: f, loop: l, total }) => (
                          <button
                            className={
                              "loop-row " +
                              (l.id === nav.loopId ? "selected" : "")
                            }
                            key={l.id}
                            onClick={() => selectLoop(l, f)}
                          >
                            <GitBranch size={13} />
                            <div>
                              <b>
                                {hex(l.pcs[0])}{" "}
                                <span>
                                  {l.kind === "natural"
                                    ? "loop"
                                    : "irreducible cycle"}{" "}
                                  · {l.pcs.length} instr
                                </span>
                              </b>
                              <small>
                                {shortFunction(f.name)}
                                {l.children.length
                                  ? ` · ${l.children.length} children`
                                  : ""}
                                {l.confidence === "partial-cfg"
                                  ? " · partial CFG"
                                  : ""}
                              </small>
                            </div>
                            <strong>{compact(total)}</strong>
                          </button>
                        ))}
                      </div>
                      {!loops.length && (
                        <div className="empty-inline">
                          No measured instructions in detected cyclic regions
                          for this scope.
                        </div>
                      )}
                    </>
                  ) : operatorTab === "mix" ? (
                    <>
                      <h3>
                        {loop ? "Selected loop" : "Selected event"} instruction
                        mix
                      </h3>
                      <Mix
                        counts={counts}
                        data={data}
                        pcs={loop?.pcs || Object.keys(counts)}
                      />
                      <div className="metric-pairs">
                        <span>
                          Function body (exclusive PC attribution)
                          <b>
                            {exact(functionTotals.get(nav.functionId) || 0n)}
                          </b>
                        </span>
                        <span>
                          Inclusive scope total
                          <b>
                            {event?.evidence === "unavailable"
                              ? "Unavailable"
                              : exact(event?.total || "0")}
                          </b>
                        </span>
                        {selectedNode && (
                          <>
                            <span>
                              Logical MACs · derived graph estimate
                              <b>{exact(selectedNode.logical_macs)}</b>
                            </span>
                            <span>
                              Executed products · derived backend estimate
                              <b>
                                {selectedNode.executed_products === null
                                  ? "Unavailable"
                                  : exact(selectedNode.executed_products)}
                              </b>
                            </span>
                            <span>
                              Instructions / executed product
                              <b>
                                {selectedNode.executed_products !== null &&
                                !event?.shared &&
                                event?.evidence !== "unavailable" &&
                                BigInt(selectedNode.executed_products) > 0n
                                  ? (
                                      Number(
                                        (BigInt(event!.total) * 1000n) /
                                          BigInt(
                                            selectedNode.executed_products,
                                          ),
                                      ) / 1000
                                    ).toFixed(3)
                                  : "—"}
                              </b>
                            </span>
                          </>
                        )}
                      </div>
                      <p className="analysis-caveat">
                        Multiply instructions can implement indexing or
                        fixed-point arithmetic. Memory instructions are not
                        cache misses or DRAM transactions.
                      </p>
                    </>
                  ) : selectedNode ? (
                    <>
                      <h3>
                        Node {selectedNode.index} · {selectedNode.type}
                      </h3>
                      {selectedNode.convolution && (
                        <p className="analysis-caption">
                          Kernel {selectedNode.convolution.kernel.join("×")} ·
                          stride {selectedNode.convolution.stride.join("×")} ·
                          padding {selectedNode.convolution.padding}
                        </p>
                      )}
                      <details>
                        <summary>Operator options</summary>
                        <pre>
                          {JSON.stringify(selectedNode.options, null, 2)}
                        </pre>
                      </details>
                      {[...selectedNode.inputs, ...selectedNode.outputs].map(
                        (id, i) => {
                          const t = data.graph.tensors.find(
                            (t) => t.id === id,
                          )!;
                          return (
                            <div className="tensor" key={`${id}:${i}`}>
                              <span className="eyebrow">
                                {i < selectedNode.inputs.length
                                  ? "INPUT"
                                  : "OUTPUT"}{" "}
                                · TENSOR {t.id}
                              </span>
                              <b>
                                {t.shape.join(" × ")}{" "}
                                <span>
                                  {t.type}
                                  {t.constant ? " · constant" : ""}
                                </span>
                              </b>
                              <small>{t.name}</small>
                              {t.quantization && (
                                <details>
                                  <summary>
                                    Quantization ·{" "}
                                    {t.quantization.scales.length} scales · axis{" "}
                                    {t.quantization.axis}
                                  </summary>
                                  <pre>
                                    {JSON.stringify(t.quantization, null, 2)}
                                  </pre>
                                </details>
                              )}
                            </div>
                          );
                        },
                      )}
                    </>
                  ) : (
                    <div className="analysis-caption">
                      Select a model operator to inspect its tensors.
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>
          <CompilationInspector
            data={data}
            node={selectedNode || null}
            activeUnitId={event?.unitId || null}
            getText={getText}
            onSource={(file, line) => {
              const pc = Object.keys(data.instructions).find((p) =>
                data.instructions[p].frames.some(
                  (f) => f.file === file && f.line === line,
                ),
              );
              if (pc) selectPc(pc, { sourcePath: file, line });
              else navigate({ sourcePath: file, line });
            }}
          />
          <section className="advanced" ref={compilerPanel}>
            <button
              className="advanced-toggle"
              onClick={() => setAdvanced(!advanced)}
              aria-expanded={advanced}
            >
              {advanced ? (
                <ChevronDown size={15} />
              ) : (
                <ChevronRight size={15} />
              )}
              <GitBranch size={15} />
              <strong>Advanced Analysis</strong>
              <span>GIMPLE · RTL · optimization remarks</span>
              <span className="chip">
                {data.compilerUnits.length
                  ? `${data.compilerUnits.length} verified units`
                  : "Optional compiler evidence"}
              </span>
            </button>
            {advanced && (
              <Advanced
                data={data}
                fn={fn}
                getText={getText}
                focus={compilerFocus}
              />
            )}
          </section>
          <footer className="app-footer">
            <span>
              <Check size={12} /> Exact runtime attribution <i /> Best-effort
              source correspondence
            </span>
            <span>
              Static CFG edges · no dynamic branch trace <i /> Instruction
              counts ≠ cycles
            </span>
          </footer>
        </>
      )}
      {active && data && inspection?.kind === "register" && (
        <RegisterInspector
          data={data}
          selection={inspection}
          onClose={() => setInspection(null)}
          onDeclaration={(file, line) => navigate({ sourcePath: file, line })}
          nodeId={event?.nodeId || null}
          onInstruction={(pc) => selectPc(pc)}
          onCompiler={(origin) => {
            setInspection(null);
            setAdvanced(true);
            setCompilerFocus({
              unitId: origin.unitId,
              artifactPath: origin.artifactPath,
              startLine: origin.startLine,
              endLine: origin.endLine,
              request: (compilerFocus?.request || 0) + 1,
            });
          }}
        />
      )}
      {active &&
        data &&
        inspection?.kind === "instruction" &&
        data.instructions[inspection.pc] && (
          <InstructionInspector
            instruction={data.instructions[inspection.pc]}
            displayOperands={formatAssemblyOperands(
              data.instructions[inspection.pc],
            )}
            selection={inspection}
            onTarget={
              data.instructions[
                data.instructions[inspection.pc].transfer.target || ""
              ]
                ? () =>
                    selectPc(data.instructions[inspection.pc].transfer.target!)
                : undefined
            }
            onClose={() => setInspection(null)}
          />
        )}
      {active && data && inspection?.kind === "source" && (
        <SourceVariableInspector
          data={data}
          selection={inspection}
          nodeId={event?.nodeId || null}
          onClose={() => setInspection(null)}
        />
      )}
      {dragging && (
        <div className="drop-overlay">
          <FileArchive size={40} />
          <h2>Drop a profile bundle</h2>
          <p>Validated locally. No upload to a server.</p>
        </div>
      )}
    </div>
  );
}
