import { describe, expect, it } from "vitest";
import { matchingSourcePcs } from "./sourceMapping";
import type { Instruction, Frame } from "./types";

const frame = (file: string, line: number): Frame => ({
  file,
  line,
  function: "kernel",
  discriminator: 0,
});
const instruction = (pc: string, frames: Frame[]): Instruction => ({
  pc,
  frames,
  bits: "0x1",
  length: 2,
  mnemonic: "c.nop",
  operands: "",
  category: "integer_alu",
  functionId: "kernel",
  functionIds: ["kernel"],
  transfer: { kind: "next", target: null },
});

describe("source line to assembly correspondence", () => {
  it("includes every matching PC at any inline depth, once per physical instruction", () => {
    const instructions = {
      "100": instruction("100", [frame("helper.h", 10), frame("conv.h", 117)]),
      "102": instruction("102", [frame("conv.h", 117)]),
      "104": instruction("104", [frame("conv.h", 117), frame("conv.h", 117)]),
      "106": instruction("106", [frame("other.h", 117)]),
      "108": instruction("108", [frame("conv.h", 118)]),
    };
    expect(matchingSourcePcs(instructions, "conv.h", 117)).toEqual([
      "100",
      "102",
      "104",
    ]);
  });
  it("keeps mappings independent of runtime counts and clears unmapped lines", () => {
    const instructions = { "100": instruction("100", [frame("conv.h", 117)]) };
    // Static instructions without an execution count still correspond to their source.
    expect(matchingSourcePcs(instructions, "conv.h", 117)).toEqual(["100"]);
    expect(matchingSourcePcs(instructions, "conv.h", 116)).toEqual([]);
    expect(matchingSourcePcs(instructions, "", 117)).toEqual([]);
  });
});
