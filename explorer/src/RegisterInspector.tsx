import { useMemo } from "react";
import { ArrowUpRight } from "lucide-react";
import type { Evidence, CompilerRegisterOrigin } from "./types";
import { hex } from "./types";
import { inferRegisterExpression, locationsAt } from "./registerExpressions";
export { locationsAt } from "./registerExpressions";
import { InspectorPopover } from "./InspectorPopover";
import { RegisterProvenance } from "./RegisterProvenance";
import { registerDetails } from "./registerDetails";

export interface RegisterSelection {
  register: string;
  pc: string;
  x: number;
  y: number;
}
export function RegisterInspector({
  data,
  selection,
  onClose,
  onDeclaration,
  nodeId,
  onInstruction,
  onCompiler,
  live,
}: {
  data: Evidence;
  selection: RegisterSelection;
  onClose: () => void;
  onDeclaration: (file: string, line: number) => void;
  nodeId: string | null;
  onInstruction: (pc: string) => void;
  onCompiler?: (origin: CompilerRegisterOrigin) => void;
  live?: { pc: string; registers: string[] };
}) {
  const locations = locationsAt(
    data.registers,
    selection.register,
    selection.pc,
  );
  const inferred = useMemo(
    () =>
      locationsAt(data.registers, selection.register, selection.pc).length
        ? null
        : inferRegisterExpression(data, selection.register, selection.pc),
    [data, selection.register, selection.pc],
  );
  const hasProvenance = useMemo(
    () =>
      registerDetails(data, selection.register, selection.pc, nodeId)
        .hasEvidence,
    [data, selection.register, selection.pc, nodeId],
  );
  return (
    <InspectorPopover
      className={
        !locations.length && !inferred && hasProvenance
          ? "provenance-inspector"
          : ""
      }
      selection={selection}
      label={`Register ${selection.register}`}
      eyebrow="REGISTER CORRESPONDENCE"
      name={selection.register}
      onClose={onClose}
      footer={
        live
          ? selection.pc === live.pc
            ? "Live state before the paused instruction. Static interpretations are labeled separately."
            : "Browsing another instruction: only static evidence is shown here; no historical runtime values are available."
          : "State before this instruction executes. Names can change at other addresses; runtime values are not recorded."
      }
    >
      {live && selection.pc === live.pc && (
        <div className="register-variable">
          <span className="chip green">Live register value</span>
          <code>
            0x
            {BigInt(live.registers[Number(selection.register.slice(1))])
              .toString(16)
              .padStart(16, "0")}
          </code>
          <small>
            Signed:{" "}
            {BigInt.asIntN(
              64,
              BigInt(live.registers[Number(selection.register.slice(1))]),
            ).toString()}
          </small>
        </div>
      )}
      {!data.registers ? (
        <p>
          This bundle has no variable-location data. Re-export the profile to
          include DWARF register mappings.
        </p>
      ) : locations.length ? (
        locations.map((location, index) => {
          const variable = data.registers!.variables[location.variableId];
          const declaration = variable.declaration;
          const available =
            declaration && data.sources[declaration.file]?.archivePath;
          return (
            <div
              className="register-variable"
              key={`${location.variableId}:${index}`}
            >
              <div className="register-variable-title">
                <strong>{variable.name}</strong>
                <span className="chip">
                  {location.kind === "value"
                    ? "variable value"
                    : location.kind === "address"
                      ? "memory address"
                      : "partial variable"}
                </span>
              </div>
              <code>{variable.type}</code>
              <small>
                {variable.function} · {variable.kind}
              </small>
              {location.kind !== "value" && <p>{location.description}</p>}
              {declaration && (
                <button
                  className="register-declaration"
                  disabled={!available}
                  onClick={() =>
                    onDeclaration(declaration.file, declaration.line)
                  }
                  title={
                    available ? declaration.file : "Source snapshot unavailable"
                  }
                >
                  <ArrowUpRight size={12} />
                  {declaration.file.split("/").pop()}:{declaration.line}
                </button>
              )}
              <details>
                <summary>Debug evidence</summary>
                <code>{location.expression}</code>
                <small>
                  {hex(location.low)} ≤ PC &lt; {hex(location.high)}
                </small>
              </details>
            </div>
          );
        })
      ) : inferred ? (
        <div className="register-variable register-inferred">
          <span className="chip">Inferred expression</span>
          <code className="register-expression">{inferred.text}</code>
          <p>
            Derived from static instructions and DWARF variable locations. This
            expression is not a compiler-recorded variable name.
          </p>
          {inferred.word32 && (
            <small>
              Word operations keep the low 32 bits and sign-extend the result.
              The expression shows the computation, including that machine
              arithmetic.
            </small>
          )}
          <details>
            <summary>Instruction evidence</summary>
            {inferred.steps.map((step, index) => (
              <code key={index}>
                {hex(step.pc)} · {step.description}
              </code>
            ))}
            <small>
              Names refer to values at their listed debug locations. Static
              incoming paths agree; no execution path or runtime value is
              inferred.
            </small>
          </details>
        </div>
      ) : hasProvenance ? null : (
        <p>
          No C++ variable location is recorded for <b>{selection.register}</b>{" "}
          at this address. It may hold a compiler temporary, a reused value, or
          a variable whose location is unavailable. A safe expression could not
          be derived from the available instructions.
        </p>
      )}
      {!locations.length && !inferred && (
        <RegisterProvenance
          data={data}
          register={selection.register}
          pc={selection.pc}
          nodeId={nodeId}
          onDeclaration={onDeclaration}
          onInstruction={onInstruction}
          onCompiler={onCompiler}
          live={Boolean(live)}
        />
      )}
    </InspectorPopover>
  );
}
