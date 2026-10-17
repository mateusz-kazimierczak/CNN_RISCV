import { useEffect, useState } from "react";
import type { Evidence, GraphNode, MemoryPlan } from "./types";
import { exact } from "./types";
import "./compilation.css";

function PlannedMemory({ plan }: { plan: MemoryPlan }) {
  const [selected, setSelected] = useState("");
  const last = Math.max(1, ...plan.requests.map((r) => r.end));
  const placements = new Map(plan.placements.map((p) => [p.name, p.offset]));
  const request = plan.requests.find((r) => r.name === selected);
  return (
    <div data-testid="planned-memory">
      <p>
        Compiler-known plan · inclusive lifetimes · execution steps, not elapsed
        time.
      </p>
      <div className="compilation-metrics">
        <span>
          Workspace capacity <b>{exact(String(plan.arena_bytes))} bytes</b>
        </span>
        <span>
          Peak live activations{" "}
          <b>{exact(String(plan.summary.peak_live_activation_bytes))} bytes</b>
        </span>
        <span>
          Peak live scratch{" "}
          <b>{exact(String(plan.summary.peak_live_scratch_bytes))} bytes</b>
        </span>
        <span>
          Planned read-only layout{" "}
          <b>{exact(String(plan.rodata_bytes))} bytes</b>
        </span>
      </div>
      <p>
        Stack peak:{" "}
        {plan.summary.stack_peak_bytes == null
          ? "unavailable"
          : String(plan.summary.stack_peak_bytes)}
        . Interpreter metadata and reserved RAM are separate accounting
        categories.
      </p>
      <svg
        className="memory-chart"
        viewBox="0 0 1000 300"
        role="img"
        aria-label="Planned memory offsets over execution steps"
      >
        <text x="55" y="16">
          Workspace offset (bytes)
        </text>
        {[0, 0.25, 0.5, 0.75, 1].map((fraction) => (
          <g key={fraction}>
            <line
              x1="65"
              x2="975"
              y1={35 + fraction * 210}
              y2={35 + fraction * 210}
              stroke="#3b5260"
            />
            <text x="62" y={39 + fraction * 210} textAnchor="end">
              {Math.round(fraction * plan.arena_bytes).toLocaleString()}
            </text>
          </g>
        ))}
        {plan.requests.map((r) => {
          const offset = placements.get(r.name);
          if (offset === null || offset === undefined) return null;
          return (
            <rect
              key={r.name}
              tabIndex={0}
              role="button"
              aria-label={`Storage ${r.name}`}
              x={65 + ((r.start + 1) / (last + 2)) * 910}
              y={35 + (offset / Math.max(1, plan.arena_bytes)) * 210}
              width={((r.end - r.start + 1) / (last + 2)) * 910}
              height={Math.max(
                1,
                (r.size_bytes / Math.max(1, plan.arena_bytes)) * 210,
              )}
              fill={
                r.category === "scratch"
                  ? "#dfb45e"
                  : `hsl(${(r.start * 19 + 180) % 360},40%,50%)`
              }
              opacity={selected && selected !== r.name ? 0.35 : 0.85}
              stroke={selected === r.name ? "white" : "#0c1b23"}
              onClick={() => setSelected(r.name)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setSelected(r.name);
                }
              }}
            >
              <title>
                {r.name}: offset {offset}; {r.size_bytes} bytes; steps {r.start}
                …{r.end} inclusive; {r.category}
              </title>
            </rect>
          );
        })}
        {Array.from(
          new Set([
            -1,
            Math.floor(last / 4),
            Math.floor(last / 2),
            Math.floor((last * 3) / 4),
            last,
          ]),
        )
          .filter((step) => step !== 0 || last < 8)
          .map((step) => (
            <text key={step} x={65 + ((step + 1) / (last + 2)) * 910} y="266">
              {step}
            </text>
          ))}
        <text x="500" y="291" textAnchor="middle">
          Execution steps (−1 input setup; final step output handoff)
        </text>
      </svg>
      {request && (
        <p role="status">
          {request.name} · offset {placements.get(request.name)} ·{" "}
          {request.size_bytes} bytes · steps {request.start} through{" "}
          {request.end}, inclusive · {request.category}
        </p>
      )}
      <details>
        <summary>
          Storage groups, offsets and lifetimes ({plan.requests.length})
        </summary>
        <div className="compilation-table">
          <table>
            <thead>
              <tr>
                <th>Group</th>
                <th>Offset</th>
                <th>Bytes</th>
                <th>First step</th>
                <th>Last step</th>
                <th>Category</th>
              </tr>
            </thead>
            <tbody>
              {plan.requests.map((r) => (
                <tr key={r.name} onClick={() => setSelected(r.name)}>
                  <td>{r.name}</td>
                  <td>{placements.get(r.name) ?? "none"}</td>
                  <td>{r.size_bytes}</td>
                  <td>{r.start}</td>
                  <td>{r.end}</td>
                  <td>{r.category}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <details>
        <summary>
          Tensor offsets and alias relationships ({plan.aliases.length}{" "}
          {plan.aliases.length === 1 ? "decision" : "decisions"})
        </summary>
        {plan.aliases.map((a) => (
          <p key={`${a.node}:${a.output}`}>
            Step {a.node}: tensor {a.output}{" "}
            {a.enabled
              ? `aliases tensor ${a.source}`
              : "keeps separate storage"}{" "}
            · {a.reason}
          </p>
        ))}
        <pre>
          {JSON.stringify(
            {
              aliases: plan.aliases,
              tensors: plan.tensors,
              scratch: plan.scratch,
            },
            null,
            2,
          )}
        </pre>
      </details>
      <p>
        Placement: {plan.algorithm}; base alignment {plan.arena_alignment}{" "}
        bytes. Alias groups share one physical allocation and the union of their
        lifetimes.
      </p>
    </div>
  );
}

export function CompilationInspector({
  data,
  node,
  activeUnitId,
  onSource,
  getText,
}: {
  data: Evidence;
  node: GraphNode | null;
  activeUnitId: string | null;
  onSource: (file: string, line: number) => void;
  getText: (path: string) => Promise<string>;
}) {
  const [unitId, setUnitId] = useState(
    activeUnitId || data.executionPlan.units[0]?.id || "",
  );
  const [artifact, setArtifact] = useState({ path: "", text: "" });
  useEffect(() => {
    setUnitId(
      activeUnitId || node?.unitIds[0] || data.executionPlan.units[0]?.id || "",
    );
  }, [data, node, activeUnitId]);
  useEffect(() => {
    setArtifact({ path: "", text: "" });
  }, [data]);
  const unit = data.executionPlan.units.find((u) => u.id === unitId);
  const prepared = data.preparedParameters?.nodes.filter((p) =>
    unit?.nodes.includes(String(p.node)),
  );
  return (
    <details
      className="compilation-inspector"
      data-testid="compilation-inspector"
    >
      <summary>
        Compilation and memory plan{" "}
        <span>
          {data.executionPlan.units.length} execution units ·{" "}
          {data.memoryPlan
            ? "verified compiler artifacts"
            : "memory plan unavailable"}
        </span>
      </summary>
      <div className="compilation-content">
        {data.measurementSummary && (
          <details>
            <summary>Build metrics · scope, unit and evidence</summary>
            <div className="compilation-table">
              <table>
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Value</th>
                    <th>Unit</th>
                    <th>Scope</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries({
                    ...data.measurementSummary.inference,
                    ...data.measurementSummary.footprint,
                  }).map(([name, m]) => (
                    <tr key={name}>
                      <td>{name.replaceAll("_", " ")}</td>
                      <td>
                        {m.value === null
                          ? "Unavailable"
                          : typeof m.value === "string"
                            ? exact(m.value)
                            : `${exact(m.value.numerator)} / ${exact(m.value.denominator)}`}
                      </td>
                      <td>{m.unit}</td>
                      <td>{m.scope}</td>
                      <td>{m.evidence}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
        <h3>Execution plan</h3>
        <p>
          {data.provenance.captureAdapter === "compiler-v2"
            ? "Compiler-known metadata describes the build."
            : "Capture-adapter metadata relates graph origins to observed calls."}{" "}
          Runtime event histograms measure retired instructions. DWARF and GCC
          mappings describe optimized code correspondence; register values were
          not captured.
        </p>
        {node && (
          <p>
            Logical node {node.index} →{" "}
            {node.unitIds.join(", ") || `eliminated: ${node.reason}`}
          </p>
        )}
        <label>
          Execution unit{" "}
          <select
            aria-label="Execution unit"
            value={unitId}
            onChange={(e) => setUnitId(e.target.value)}
          >
            {data.executionPlan.units.map((u) => (
              <option key={u.id} value={u.id}>
                {u.order} · {u.id} · {u.symbol}
              </option>
            ))}
          </select>
        </label>
        {unit && (
          <div data-testid="execution-unit-details">
            <dl>
              <dt>Implementation</dt>
              <dd>{unit.implementation}</dd>
              <dt>Arithmetic backend</dt>
              <dd>{unit.arithmetic_backend}</dd>
              <dt>Logical origins</dt>
              <dd>
                {unit.nodes.join(", ")}
                {unit.nodes.length > 1 &&
                  " · shared measurement; full cost, not apportioned"}
              </dd>
              <dt>Observed events</dt>
              <dd>
                {unit.eventIds.join(", ") || "Unavailable"} · inclusive of
                callees
              </dd>
              <dt>Operands</dt>
              <dd>
                Inputs {unit.inputs.join(", ")} → outputs{" "}
                {unit.outputs.join(", ")}
              </dd>
              <dt>Work estimates</dt>
              <dd>
                Logical MACs{" "}
                {unit.work.logical_macs === null
                  ? "unavailable"
                  : exact(unit.work.logical_macs)}
                ; backend products{" "}
                {unit.work.executed_products === null
                  ? "unavailable"
                  : exact(unit.work.executed_products)}{" "}
                · {unit.work.evidence} · {unit.work.policy}
              </dd>
            </dl>
            {unit.source && (
              <button
                onClick={() => onSource(unit.source!.file, unit.source!.line)}
              >
                Generated source · {unit.source.file}:{unit.source.line}–
                {unit.source.end_line}
              </button>
            )}
            {unit.notes.map((n, i) => (
              <p key={i}>{n}</p>
            ))}
            <details>
              <summary>Prepared parameters · compiler-known values</summary>
              <pre>
                {prepared?.length
                  ? JSON.stringify(
                      prepared.map(({ node, integers, ...rest }) => ({
                        node,
                        integers,
                        ...rest,
                      })),
                      null,
                      2,
                    )
                  : "Unavailable for this build"}
              </pre>
            </details>
            <details>
              <summary>Operand memory requirements and choices</summary>
              <pre>
                {unit.memory
                  ? JSON.stringify(unit.memory, null, 2)
                  : "Unavailable for this build"}
              </pre>
            </details>
          </div>
        )}
        <h3>Planned memory</h3>
        {data.memoryPlan ? (
          <PlannedMemory plan={data.memoryPlan} />
        ) : (
          <p>
            No compiler memory plan is available. Any allocation scope is a
            separately measured setup event.
          </p>
        )}
        {!!data.executionPlan.artifacts?.length && (
          <details>
            <summary>Supporting artifacts · saved build evidence</summary>
            {data.executionPlan.artifacts.map((a) => (
              <button
                key={a.archivePath}
                onClick={async () => {
                  setArtifact({ path: a.archivePath, text: "Loading…" });
                  try {
                    const text = await getText(a.archivePath);
                    setArtifact({ path: a.archivePath, text });
                  } catch (e) {
                    setArtifact({ path: a.archivePath, text: String(e) });
                  }
                }}
              >
                {a.name} · SHA-256 {a.sha256.slice(0, 12)}
              </button>
            ))}
            {artifact.path && (
              <>
                <p>{artifact.path}</p>
                <pre>{artifact.text}</pre>
              </>
            )}
          </details>
        )}
      </div>
    </details>
  );
}
