import { useEffect, useMemo, useState } from "react";
import type { Evidence, Func, CompilerUnit, Artifact } from "./types";
import { CodeView, DiffView } from "./CodeView";
const stages = [
  "Original tree",
  "Initial GIMPLE",
  "Inlining analysis",
  "Optimized GIMPLE",
  "RTL expansion",
  "Final RTL",
  "Emitted assembly",
  "Optimization remarks",
  "Pass discovery",
];
export interface CompilerFocus {
  unitId: string;
  artifactPath: string;
  startLine: number;
  endLine: number;
  request: number;
}
const sameLinkage = (a: string, b: string) =>
  a === b || a.split(".")[0] === b.split(".")[0];
function matching(artifact: Artifact, fn: Func) {
  const exact = artifact.functions.find((f) =>
    fn.linkageNames.some((n) => sameLinkage(n, f.linkageName)),
  );
  if (exact) return exact;
  const stem = fn.name.split("(")[0].trim();
  const candidates = artifact.functions.filter(
    (f) => f.linkageName.startsWith("source:") && f.name.includes(stem + " ("),
  );
  return candidates.length === 1 ? candidates[0] : undefined;
}
export function Advanced({
  data,
  fn,
  getText,
  focus,
}: {
  data: Evidence;
  fn: Func | null;
  getText: (path: string) => Promise<string>;
  focus?: CompilerFocus | null;
}) {
  const [unitId, setUnitId] = useState(""),
    [stage, setStage] = useState("Optimized GIMPLE"),
    [raw, setRaw] = useState(false),
    [diff, setDiff] = useState(false),
    [query, setQuery] = useState(""),
    [selectedFunction, setSelectedFunction] = useState(""),
    [texts, setTexts] = useState({ text: "", before: "", status: "" });
  const suggested = useMemo(
    () =>
      fn
        ? data.compilerUnits.find((u) =>
            u.artifacts.some((a) => matching(a, fn)),
          )
        : undefined,
    [data, fn],
  );
  useEffect(() => {
    setUnitId(suggested?.id || "");
    setSelectedFunction("");
  }, [suggested, fn?.id]);
  useEffect(() => {
    if (!focus) return;
    const unit = data.compilerUnits.find((u) => u.id === focus.unitId);
    const artifact = unit?.artifacts.find(
      (a) => a.archivePath === focus.artifactPath,
    );
    if (unit && artifact) {
      setUnitId(unit.id);
      setStage(artifact.stage);
      setSelectedFunction("");
      setRaw(false);
      setDiff(false);
      setQuery("");
    }
  }, [focus, data]);
  const unit = data.compilerUnits.find((u) => u.id === unitId);
  const artifacts = useMemo(
    () =>
      unit
        ? [...unit.artifacts].sort(
            (a, b) => stages.indexOf(a.stage) - stages.indexOf(b.stage),
          )
        : [],
    [unit],
  );
  const artifact = artifacts.find((a) => a.stage === stage) || artifacts[0];
  const artifactIndex = artifact ? artifacts.indexOf(artifact) : -1;
  const functions =
    artifact?.functions.filter(
      (f) =>
        !query ||
        `${f.name} ${f.linkageName}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    ) || [];
  const active =
    artifact?.functions.find((f) => f.linkageName === selectedFunction) ||
    (artifact && fn ? matching(artifact, fn) : undefined);
  useEffect(() => {
    let cancelled = false;
    if (!artifact) {
      setTexts({ text: "", before: "", status: "" });
      return;
    }
    const slice = async (a: Artifact) => {
      const text = await getText(a.archivePath);
      if (raw) return text;
      const f =
        a.functions.find((f) => f.linkageName === selectedFunction) ||
        (fn ? matching(a, fn) : undefined);
      return f
        ? text
            .split("\n")
            .slice(f.startLine - 1, f.endLine)
            .join("\n")
        : text;
    };
    setTexts({ text: "", before: "", status: "Loading compiler evidence…" });
    Promise.all([
      slice(artifact),
      diff && artifactIndex > 0
        ? slice(artifacts[artifactIndex - 1])
        : Promise.resolve(""),
    ])
      .then(([text, before]) => {
        if (!cancelled)
          setTexts({
            text,
            before,
            status:
              !raw && !active
                ? "No function-level match in this artifact; showing searchable raw text."
                : "",
          });
      })
      .catch((e) => {
        if (!cancelled) setTexts({ text: "", before: "", status: String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [
    artifact,
    artifactIndex,
    artifacts,
    raw,
    diff,
    selectedFunction,
    fn,
    getText,
    active,
  ]);
  return (
    <section className="advanced-content">
      <div className="advanced-note">
        Compiler representations and remarks are static evidence. Counts and
        estimates in dumps are GCC estimates, not Spike measurements. Linker
        relaxation can change emitted instruction addresses.
      </div>
      {!data.compilerUnits.length ? (
        <div className="empty-inline">
          Compiler evidence is not included in this bundle. Import a bundle that
          includes verified GCC analysis.
        </div>
      ) : (
        <>
          <div className="advanced-tools">
            <select
              aria-label="Compiler unit"
              value={unitId}
              onChange={(e) => {
                setUnitId(e.target.value);
                setSelectedFunction("");
              }}
            >
              <option value="">
                {suggested
                  ? "Select compilation unit"
                  : "No matching compiler unit — choose raw evidence"}
              </option>
              {data.compilerUnits.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.source.split("/").slice(-4).join("/")}
                </option>
              ))}
            </select>
            <select
              aria-label="Compiler stage"
              value={artifact?.stage || stage}
              onChange={(e) => {
                setStage(e.target.value);
                setSelectedFunction("");
              }}
            >
              {artifacts.map((a) => (
                <option key={a.path}>{a.stage}</option>
              ))}
            </select>
            <label>
              <input
                type="checkbox"
                checked={raw}
                onChange={(e) => setRaw(e.target.checked)}
              />{" "}
              Full raw dump
            </label>
            <label>
              <input
                type="checkbox"
                checked={diff}
                disabled={artifactIndex < 1}
                onChange={(e) => setDiff(e.target.checked)}
              />{" "}
              Compare preceding stage
            </label>
          </div>
          {unit && (
            <>
              <div className="advanced-tools">
                <input
                  aria-label="Search compiler functions"
                  placeholder="Find a function in this stage…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                <select
                  aria-label="Compiler function"
                  value={active?.linkageName || ""}
                  onChange={(e) => setSelectedFunction(e.target.value)}
                >
                  <option value="">
                    {active
                      ? "Selected machine-code function"
                      : "Raw text / no matching function"}
                  </option>
                  {functions.map((f, i) => (
                    <option key={f.linkageName + ":" + i} value={f.linkageName}>
                      {f.name}
                    </option>
                  ))}
                </select>
                <span className="chip green">Loadable bytes verified</span>
              </div>
              {texts.status && (
                <div className="advanced-note">{texts.status}</div>
              )}
              <div className="compiler-editor">
                {diff && artifactIndex > 0 ? (
                  <DiffView before={texts.before} after={texts.text} />
                ) : (
                  <CodeView
                    text={texts.text}
                    language={
                      artifact?.stage === "Emitted assembly"
                        ? "riscv"
                        : "plaintext"
                    }
                    label="Compiler artifact"
                    line={
                      focus?.artifactPath === artifact?.archivePath
                        ? Math.max(
                            1,
                            focus.startLine -
                              (!raw && active ? active.startLine - 1 : 0),
                          )
                        : 1
                    }
                    decorations={
                      focus?.artifactPath === artifact?.archivePath
                        ? Array.from(
                            {
                              length: Math.min(
                                32,
                                focus.endLine - focus.startLine + 1,
                              ),
                            },
                            (_, i) => ({
                              line: Math.max(
                                1,
                                focus.startLine +
                                  i -
                                  (!raw && active ? active.startLine - 1 : 0),
                              ),
                              className: "code-selected",
                            }),
                          )
                        : []
                    }
                  />
                )}
              </div>
              <details className="command-details">
                <summary>Recorded command & dependency provenance</summary>
                <pre>
                  {JSON.stringify(
                    {
                      directory: unit.directory,
                      arguments: unit.arguments,
                      dependencies: unit.dependencyHashes,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </>
          )}
        </>
      )}
    </section>
  );
}
