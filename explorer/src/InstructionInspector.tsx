import { hex, type Instruction } from "./types";
import { InspectorPopover, type InspectorAnchor } from "./InspectorPopover";
import { explainInstruction } from "./instructionHelp";

export type InstructionSelection = InspectorAnchor;
export function InstructionInspector({
  instruction,
  selection,
  onClose,
  displayOperands,
  onTarget,
}: {
  instruction: Instruction;
  selection: InstructionSelection;
  onClose: () => void;
  displayOperands?: string;
  onTarget?: () => void;
}) {
  const help = explainInstruction(instruction);
  const operands = displayOperands ?? instruction.operands.split("#")[0].trim();
  const target = instruction.transfer.target
    ? hex(instruction.transfer.target)
    : "";
  const targetIndex = onTarget && target ? operands.indexOf(target) : -1;
  return (
    <InspectorPopover
      className="instruction-inspector"
      selection={selection}
      label={`Instruction ${instruction.mnemonic}`}
      eyebrow="INSTRUCTION REFERENCE"
      name={instruction.mnemonic}
      onClose={onClose}
      footer={
        <>
          {instruction.length * 8}-bit encoding · RV64
          {help.reference && (
            <>
              {" "}
              ·{" "}
              <a href={help.reference} target="_blank" rel="noreferrer">
                RISC-V specification ↗
              </a>
            </>
          )}
        </>
      }
    >
      <div className="register-variable instruction-help">
        <strong>{help.title}</strong>
        <code>
          {instruction.mnemonic}{" "}
          {targetIndex >= 0 ? (
            <>
              {operands.slice(0, targetIndex)}
              <button
                className="assembly-address-button"
                aria-label={`Go to ${target}`}
                onClick={onTarget}
              >
                {target}
              </button>
              {operands.slice(targetIndex + target.length)}
            </>
          ) : (
            operands
          )}
        </code>
        <p>{help.description}</p>
        {help.operation && (
          <code className="instruction-operation">{help.operation}</code>
        )}
        {help.equivalent && (
          <div className="instruction-equivalent">
            <small>Uncompressed equivalent</small>
            <code>{help.equivalent}</code>
          </div>
        )}
        {help.notes.map((note, index) => (
          <p key={index}>{note}</p>
        ))}
        {displayOperands !== undefined &&
          displayOperands !== instruction.operands && (
            <details>
              <summary>Original disassembly</summary>
              <code>
                {instruction.mnemonic} {instruction.operands}
              </code>
            </details>
          )}
      </div>
    </InspectorPopover>
  );
}
