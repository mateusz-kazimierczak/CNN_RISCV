import { ArrowUpRight } from "lucide-react";
import type { CompilerRegisterOrigin, Evidence } from "./types";
import { hex } from "./types";
import { registerDetails, memoryRelationText } from "./registerDetails";
export function RegisterProvenance({
  data,
  register,
  pc,
  nodeId,
  onDeclaration,
  onInstruction,
  onCompiler,
  live = false,
}: {
  data: Evidence;
  register: string;
  pc: string;
  nodeId: string | null;
  onDeclaration: (file: string, line: number) => void;
  onInstruction: (pc: string) => void;
  onCompiler?: (origin: CompilerRegisterOrigin) => void;
  live?: boolean;
}) {
  const info = registerDetails(data, register, pc, nodeId);
  const { role } = info;
  const loopFrame =
    role &&
    data.instructions[role.comparePc].frames.find((f) => f.file && f.line);
  const relationshipEvidence = [...info.relations, ...info.nearbyRelations];
  if (!info.hasEvidence) return null;
  const name = info.variables.length === 1 ? info.variables[0].name : null;
  const title =
    role?.kind === "pointer"
      ? name
        ? `Pointer used for ${name}`
        : "Loop pointer"
      : role?.kind === "boundary"
        ? role.span
          ? "Loop end pointer"
          : "Loop boundary"
        : info.relations.length
          ? "Source value relationship"
          : "Register provenance";
  const instruction = (address: string) => (
    <button
      key={address}
      className="register-declaration trace-instruction"
      onClick={() => onInstruction(address)}
    >
      <ArrowUpRight size={12} />
      <code>
        {hex(address)} · {data.instructions[address].mnemonic}{" "}
        {data.instructions[address].operands
          .split("#")[0]
          .replace(/\s*<[^>]*>/g, "")
          .trim()}
      </code>
    </button>
  );
  return (
    <div className="register-variable register-provenance">
      <span className="chip">
        {role
          ? "Inferred role"
          : info.relations.length
            ? "DWARF relationship"
            : "Static instruction evidence"}
      </span>
      <code className="register-expression">{title}</code>
      {relationshipEvidence.map((relation, i) => (
        <div key={i}>
          <small>
            {info.relations.includes(relation)
              ? "Compiler-recorded relationship at this PC"
              : `Nearby DWARF relationship; valid before ${hex(relation.high)}`}
          </small>
          <code className="register-relation">
            {data.registers!.variables[relation.variableId].name} ={" "}
            {memoryRelationText(register, relation)}
          </code>
        </div>
      ))}
      {role?.kind === "pointer" && (
        <p>
          Advances by {role.stride} {role.stride === 1 ? "byte" : "bytes"} each
          loop iteration
          {role.relatedRegister
            ? `; compared with ${role.relatedRegister}`
            : ""}
          .
        </p>
      )}
      {role?.kind === "boundary" && (
        <p>
          Compared with the advancing pointer in {role.relatedRegister}. This
          register stays unchanged within this loop.
        </p>
      )}
      {role?.span && (
        <>
          <code className="register-relation">
            {role.kind === "boundary" ? register : role.relatedRegister} =
            initial({role.kind === "boundary" ? role.relatedRegister : register}
            ) + {role.span.source?.name || `span from ${role.span.register}`}
          </code>
          {info.span?.kind === "fixed" && (
            <small>
              Model-derived span: {info.span.value} bytes for the selected
              operator.
            </small>
          )}
        </>
      )}
      {info.origins.length > 0 && (
        <small>
          Compiler origin:{" "}
          {[...new Set(info.origins.map((o) => o.name))].join(" / ")} · final
          RTL
        </small>
      )}
      {info.variables.map(
        (variable) =>
          variable.declaration && (
            <button
              key={variable.id}
              className="register-declaration"
              disabled={!data.sources[variable.declaration.file]?.archivePath}
              onClick={() =>
                onDeclaration(
                  variable.declaration!.file,
                  variable.declaration!.line,
                )
              }
            >
              <ArrowUpRight size={12} />
              {variable.name} · {variable.declaration.file.split("/").pop()}:
              {variable.declaration.line}
            </button>
          ),
      )}
      <details>
        <summary>Supporting evidence</summary>
        {loopFrame && (
          <button
            className="register-declaration"
            onClick={() => onDeclaration(loopFrame.file!, loopFrame.line!)}
          >
            <ArrowUpRight size={12} />
            Loop source · {loopFrame.file!.split("/").pop()}:{loopFrame.line}
          </button>
        )}
        {role?.span?.source && (
          <button
            className="register-declaration"
            onClick={() =>
              onDeclaration(role.span!.source!.file, role.span!.source!.line)
            }
          >
            <ArrowUpRight size={12} />
            {role.span.source.name} · {role.span.source.file.split("/").pop()}:
            {role.span.source.line}
          </button>
        )}
        {relationshipEvidence.map((relation, i) => (
          <div key={i}>
            <small>
              DWARF: {hex(relation.low)} ≤ PC &lt; {hex(relation.high)}
            </small>
            <code>{relation.expression}</code>
          </div>
        ))}
        {role ? (
          <>
            <small>Load and pointer-update instructions</small>
            {[...new Set([...role.loadPcs, ...role.updatePcs])].map(
              instruction,
            )}
            <small>Loop comparison</small>
            {instruction(role.comparePc)}
            {role.span && (
              <>
                <small>
                  Static add/copy analysis proves end − initial pointer equals
                  this scalar definition, in bytes:
                </small>
                {instruction(role.span.definitionPc)}
              </>
            )}
          </>
        ) : (
          <>
            <small>Uses in the containing basic block (static order)</small>
            {info.uses.map(instruction)}
          </>
        )}
        {onCompiler &&
          info.origins.map((origin, i) => (
            <div key={i}>
              <button
                className="register-declaration"
                onClick={() => onCompiler(origin)}
              >
                <ArrowUpRight size={12} />
                Open final RTL · {origin.name}
              </button>
              <small>
                Unique loop-window match in final RTL and emitted assembly,
                including the backedge. Verified against measured executable
                code.
              </small>
            </div>
          ))}
        <small>
          {live
            ? "Static interpretation; live values are shown separately at the paused PC."
            : "No current pointer address, memory contents, iteration number, or dynamic branch sequence is recorded."}
        </small>
      </details>
    </div>
  );
}
