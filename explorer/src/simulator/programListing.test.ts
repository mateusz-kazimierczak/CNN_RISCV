import { describe, expect, it } from "vitest";
import type { Func, Instruction } from "../types";
import {
  backendInstruction,
  buildProgramListing,
  instructionAddress,
  programDecorations,
} from "./programListing";

const ins = (
  pc: string,
  length = 2,
  functionId: string | null = null,
): Instruction => ({
  pc: BigInt(pc).toString(),
  length,
  bits: "1",
  mnemonic: "c.nop",
  operands: "",
  category: "integer_alu",
  functionId,
  functionIds: functionId ? [functionId] : [],
  frames: [],
  transfer: { kind: "none", target: null },
});
const fn = (id: string, address: string, pcs: string[]): Func => ({
  id,
  name: id,
  aliases: [],
  linkageNames: [],
  address: BigInt(address).toString(),
  size: 8,
  pcs,
  cfg: { blocks: [], loops: [], complete: true, unresolved: [] },
});
const fixture = () => {
  const a = ins("0x1000000000000000", 2, "first"),
    b = ins("0x1000000000000002", 4, "first"),
    c = ins("0x1000000000000010", 2, "second");
  a.mnemonic = "jal";
  a.operands = `x1,${BigInt(c.pc).toString(16)}`;
  a.transfer = { kind: "call", target: c.pc };
  a.frames = [
    { file: "shared.h", line: 7, function: "first", discriminator: 0 },
    { file: "shared.h", line: 7, function: "outer", discriminator: 0 },
  ];
  c.frames = [
    { file: "shared.h", line: 7, function: "second", discriminator: 0 },
  ];
  const instructions = { [c.pc]: c, [b.pc]: b, [a.pc]: a };
  return {
    a,
    b,
    c,
    data: {
      instructions,
      functions: [fn("first", a.pc, [a.pc, b.pc]), fn("second", c.pc, [c.pc])],
    },
  };
};
describe("whole program navigation", () => {
  it("orders exact addresses once, keeps compressed lengths, symbols, gaps, and cross-function links", () => {
    const { a, b, c, data } = fixture();
    const listing = buildProgramListing(data);
    expect(listing.pcs.filter(Boolean)).toEqual([a.pc, b.pc, c.pc]);
    expect(listing.count).toBe(3);
    expect(listing.text).toContain("10 bytes outside decoded code");
    expect(listing.targets.get(listing.pcToLine.get(a.pc)!)).toBe(c.pc);
    expect(listing.text).toContain("# 0x1000000000000010 · second");
    expect(listing.text.split("\n")[listing.pcToLine.get(b.pc)! - 1]).toContain(
      "c.nop",
    );
  });
  it("matches source across functions without counting duplicate inline frames twice", () => {
    const { a, c, data } = fixture(),
      listing = buildProgramListing(data);
    const marks = programDecorations(listing, a.pc, c.pc, "shared.h", 7, [
      { pc: c.pc },
      { pc: c.pc },
    ]);
    expect(
      marks.filter((m) => m.className === "source-linked").map((m) => m.line),
    ).toEqual([listing.pcToLine.get(a.pc), listing.pcToLine.get(c.pc)]);
    expect(marks.filter((m) => m.className === "sim-breakpoint")).toHaveLength(
      1,
    );
    expect(marks.find((m) => m.className === "sim-browsing-line")?.line).toBe(
      listing.pcToLine.get(c.pc),
    );
    expect(marks.find((m) => m.className === "sim-pc-line")?.line).toBe(
      listing.pcToLine.get(a.pc),
    );
  });
  it("keeps the next-PC arrow independent of breakpoints and browsing; running shows only the last stop", () => {
    const { a, c, data } = fixture(),
      listing = buildProgramListing(data);
    const breaks = [
      { pc: a.pc, node: -1 },
      { pc: a.pc, node: 4 },
      { pc: c.pc, node: 5 },
    ];
    const marks = programDecorations(listing, a.pc, c.pc, "", 1, breaks);
    const atPC = marks.filter((m) => m.line === listing.pcToLine.get(a.pc));
    expect(atPC.map((m) => m.glyph)).toEqual(["pc", "breakpoint"]);
    expect(atPC[0].label).toContain("Next instruction");
    expect(marks.find((m) => m.glyph === "stage-breakpoint")?.label).toContain(
      "stage 5",
    );
    const running = programDecorations(
      listing,
      a.pc,
      c.pc,
      "",
      1,
      breaks,
      "running",
    );
    expect(running.some((m) => m.glyph === "pc")).toBe(false);
    expect(running.find((m) => m.glyph === "last-pc")?.label).toContain(
      "running",
    );
    expect(
      programDecorations(listing, a.pc, c.pc, "", 1, breaks, "exited").some(
        (m) => ["pc", "last-pc"].includes(m.glyph || ""),
      ),
    ).toBe(false);
    expect(listing.breakableLines.has(listing.pcToLine.get(a.pc)!)).toBe(true);
    expect(listing.breakableLines.has(1)).toBe(false); // Symbol heading, not an instruction.
  });
  it("rejects data, gaps, odd/mid-instruction addresses and malformed input", () => {
    const { a, b, data } = fixture(),
      listing = buildProgramListing(data);
    expect(instructionAddress(" 0X1000000000000000 ", listing)).toBe(a.pc);
    expect(instructionAddress("1000000000000002", listing)).toBe(b.pc);
    for (const value of [
      "0x1000000000000001",
      "0x1000000000000004",
      "0x1000000000000008",
      "0x80020000",
      "-1",
      "pc",
      "1;step",
    ])
      expect(() => instructionAddress(value, listing)).toThrow();
  });
  it("retains unnamed instructions and merges native ROM without replacing verified ELF", () => {
    const { a, data } = fixture();
    const native = backendInstruction({
      pc: "4096",
      bits: "663",
      length: 4,
      text: "auipc t0,0x0",
    });
    const listing = buildProgramListing(data, [
      native,
      { ...a, mnemonic: "wrong" },
    ]);
    expect(listing.firstPc).toBe("4096");
    expect(listing.instructions["4096"].operands).toBe("x5,0x0");
    expect(listing.instructions[a.pc].mnemonic).toBe("jal");
    expect(listing.count).toBe(4);
    expect(listing.text).toContain("Spike reset ROM");
    expect(listing.pcs[0]).toBeNull();
    expect(
      buildProgramListing({
        functions: [],
        instructions: { [a.pc]: { ...a, functionId: null, functionIds: [] } },
      }).pcToLine.has(a.pc),
    ).toBe(true);
  });
});
