import type { Instruction } from "./types";

/** A physical instruction can correspond to the selected line at any inline depth. */
export function matchingSourcePcs(
  instructions: Record<string, Instruction>,
  file: string,
  line: number,
): string[] {
  if (!file) return [];
  return Object.values(instructions)
    .filter((instruction) =>
      instruction.frames.some(
        (frame) => frame.file === file && frame.line === line,
      ),
    )
    .map((instruction) => instruction.pc);
}
