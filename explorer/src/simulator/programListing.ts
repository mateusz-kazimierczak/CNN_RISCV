import type { Evidence, Instruction } from "../types";
import { hex } from "../types";
import { createAssemblyFormatter } from "../assemblyDisplay";
import type { Decoration } from "../CodeView";

type ProgramEvidence = Pick<Evidence, "instructions" | "functions">;
export function backendInstruction(ins: {
  pc: string;
  bits: string;
  length: number;
  text: string;
}): Instruction {
  const aliases = [
    "zero",
    "ra",
    "sp",
    "gp",
    "tp",
    "t0",
    "t1",
    "t2",
    "s0",
    "s1",
    "a0",
    "a1",
    "a2",
    "a3",
    "a4",
    "a5",
    "a6",
    "a7",
    "s2",
    "s3",
    "s4",
    "s5",
    "s6",
    "s7",
    "s8",
    "s9",
    "s10",
    "s11",
    "t3",
    "t4",
    "t5",
    "t6",
  ];
  const registers = new Map(aliases.map((name, i) => [name, `x${i}`]));
  registers.set("fp", "x8");
  const text = ins.text.trim();
  return {
    pc: ins.pc,
    bits: ins.bits,
    length: ins.length,
    mnemonic: text.split(/\s+/)[0],
    operands: text
      .replace(/^\S+\s*/, "")
      .replace(/\b[a-z][a-z0-9]*\b/g, (word) => registers.get(word) || word),
    category: "unknown",
    functionId: null,
    functionIds: [],
    frames: [],
    transfer: { kind: "none", target: null },
  };
}
export interface ProgramListing {
  text: string;
  pcs: (string | null)[];
  pcToLine: Map<string, number>;
  targets: Map<number, string>;
  sourceLines: Map<string, Map<number, Set<string>>>;
  instructions: Record<string, Instruction>;
  firstPc: string;
  count: number;
  breakableLines: Set<number>;
}

/** One row per decoded instruction, independent of symbols and runtime events.
 * Section gaps and symbols are navigation landmarks, never synthetic code. */
export function buildProgramListing(
  data: ProgramEvidence,
  native: Instruction[] = [],
): ProgramListing {
  const instructions = {
    ...Object.fromEntries(native.map((ins) => [ins.pc, ins])),
    ...data.instructions,
  };
  const ordered = Object.values(instructions).sort((a, b) =>
    BigInt(a.pc) < BigInt(b.pc) ? -1 : BigInt(a.pc) > BigInt(b.pc) ? 1 : 0,
  );
  const format = createAssemblyFormatter(data.functions);
  const starts = new Map<string, string[]>();
  for (const fn of data.functions) {
    if (!instructions[fn.address]) continue;
    starts.set(fn.address, [...(starts.get(fn.address) || []), fn.name]);
  }
  const lines: string[] = [],
    pcs: (string | null)[] = [];
  const pcToLine = new Map<string, number>(),
    targets = new Map<number, string>();
  const sourceLines = new Map<string, Map<number, Set<string>>>();
  const breakableLines = new Set<number>();
  const heading = (text: string) => {
    lines.push(`# ${text}`);
    pcs.push(null);
  };
  let previous: Instruction | undefined;
  for (const ins of ordered) {
    if (previous) {
      const end = BigInt(previous.pc) + BigInt(previous.length);
      if (end < BigInt(ins.pc))
        heading(
          `${hex(String(end))}…${hex(ins.pc)} · ${(BigInt(ins.pc) - end).toLocaleString()} bytes outside decoded code (not shown)`,
        );
    }
    if (starts.has(ins.pc))
      heading(`${hex(ins.pc)} · ${starts.get(ins.pc)!.join(" / ")}`);
    else if (
      !previous ||
      (data.instructions[previous.pc] !== undefined) !==
        (data.instructions[ins.pc] !== undefined)
    )
      heading(
        data.instructions[ins.pc]
          ? "Executable code"
          : BigInt(ins.pc) >= 0x1000n && BigInt(ins.pc) < 0x1014n
            ? "Spike reset ROM · backend disassembly, outside ELF"
            : "Native disassembly · outside ELF",
      );
    lines.push(
      `${hex(ins.pc).padEnd(14)} ${ins.mnemonic.padEnd(9)} ${format(ins)}`,
    );
    pcs.push(ins.pc);
    pcToLine.set(ins.pc, lines.length);
    if (data.instructions[ins.pc]) breakableLines.add(lines.length);
    if (ins.transfer.target && instructions[ins.transfer.target])
      targets.set(lines.length, ins.transfer.target);
    for (const frame of ins.frames) {
      if (!frame.file || !frame.line) continue;
      let byLine = sourceLines.get(frame.file);
      if (!byLine) {
        byLine = new Map();
        sourceLines.set(frame.file, byLine);
      }
      let matches = byLine.get(frame.line);
      if (!matches) {
        matches = new Set();
        byLine.set(frame.line, matches);
      }
      matches.add(ins.pc);
    }
    previous = ins;
  }
  return {
    text: lines.join("\n"),
    pcs,
    pcToLine,
    targets,
    sourceLines,
    instructions,
    firstPc: ordered[0]?.pc || "",
    count: ordered.length,
    breakableLines,
  };
}

export function programDecorations(
  listing: ProgramListing,
  stoppedPc: string,
  selectedPc: string,
  file: string,
  line: number,
  breakpoints: { pc: string; node?: number }[],
  execution: "paused" | "running" | "exited" = "paused",
): Decoration[] {
  const result: Decoration[] = [];
  const add = (pc: string, className: string) => {
    const row = listing.pcToLine.get(pc);
    if (row) result.push({ line: row, className });
  };
  const liveRow = listing.pcToLine.get(stoppedPc);
  if (liveRow && execution !== "exited")
    result.push({
      line: liveRow,
      className: execution === "paused" ? "sim-pc-line" : "sim-last-pc-line",
      glyph: execution === "paused" ? "pc" : "last-pc",
      label:
        execution === "paused"
          ? `Next instruction to execute: ${hex(stoppedPc)}`
          : `Last stopped PC: ${hex(stoppedPc)}. Execution is running.`,
    });
  if (selectedPc !== stoppedPc || execution === "exited")
    add(selectedPc, "sim-browsing-line");
  for (const pc of listing.sourceLines.get(file)?.get(line) || [])
    add(pc, "source-linked");
  for (const pc of new Set(breakpoints.map((b) => b.pc))) {
    const row = listing.pcToLine.get(pc);
    if (!row) continue;
    const matches = breakpoints.filter((b) => b.pc === pc);
    const address = matches.some((b) => b.node === undefined || b.node < 0);
    const stages = matches
      .filter((b) => b.node !== undefined && b.node >= 0)
      .map((b) => b.node)
      .join(", ");
    result.push({
      line: row,
      className: "sim-breakpoint",
      glyph: address ? "breakpoint" : "stage-breakpoint",
      label: `${address ? "Address breakpoint" : "Stage-entry breakpoint"} at ${hex(pc)}${stages ? `; stage ${stages}` : ""}`,
    });
  }
  return result;
}

export function instructionAddress(
  value: string,
  listing: ProgramListing,
): string {
  const text = value.trim();
  if (!/^(?:0x)?[0-9a-f]+$/i.test(text))
    throw new Error(
      "Enter a hexadecimal instruction address, such as 0x80005cac.",
    );
  const pc = BigInt(`0x${text.replace(/^0x/i, "")}`).toString();
  if (!listing.pcToLine.has(pc))
    throw new Error(
      "No decoded instruction starts at that address. Data, gaps, and the middle of an instruction are not selectable.",
    );
  return pc;
}
