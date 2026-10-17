import { it, expect } from "vitest";
import { assemblyTokenAt, assemblyAddressRange } from "../assemblyToken";
it("inspects instructions and registers in live listings without a retirement column", () => {
  const row = "0x80005c9c    c.addi    x14,1";
  expect(assemblyTokenAt(row, row.indexOf("c.addi") + 1)).toEqual({
    kind: "instruction",
    value: "c.addi",
  });
  expect(assemblyTokenAt(row, row.indexOf("x14") + 1)).toEqual({
    kind: "register",
    value: "x14",
  });
  expect(assemblyTokenAt(row, 1)).toBeNull();
});
it("keeps branch destinations navigable in live listings", () => {
  const row =
    "0x80005cac    bne       x27,x14,0x80005c94  # ConvPerChannel + 0x1aa";
  const range = assemblyAddressRange(row, String(0x80005c94));
  expect(range).not.toBeNull();
  expect(assemblyTokenAt(row, range!.start)).toEqual({
    kind: "address",
    value: String(0x80005c94),
  });
});

import { explainInstruction } from "../instructionHelp";
import type { Instruction } from "../types";
it("does not describe a compressed stack adjustment as having a 12-bit encoding", () => {
  const ins = {
    pc: "2147506922",
    bits: "0",
    length: 2,
    mnemonic: "c.addi16sp",
    operands: "x2,-288",
    category: "integer_alu",
    functionId: null,
    functionIds: [],
    frames: [],
    transfer: { kind: "none", target: null },
  } satisfies Instruction;
  const help = explainInstruction(ins);
  expect(help.equivalent).toBe("addi x2,x2,-288");
  expect(help.notes.join(" ")).not.toContain("encoded 12-bit");
});
