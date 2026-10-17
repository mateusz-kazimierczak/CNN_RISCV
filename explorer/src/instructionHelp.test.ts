import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { unzipSync, strFromU8 } from "fflate";
import { explainInstruction, supportedMnemonics } from "./instructionHelp";
import { assemblyTokenAt, assemblyAddressRange } from "./assemblyToken";
import type { Instruction, Evidence } from "./types";
const instruction = (
  mnemonic: string,
  operands: string,
  target: string | null = null,
): Instruction => ({
  pc: "2147506978",
  bits: "0",
  length: mnemonic.startsWith("c.") ? 2 : 4,
  mnemonic,
  operands,
  category: "",
  functionId: null,
  functionIds: [],
  frames: [],
  transfer: { kind: "next", target },
});
describe("instruction explanations", () => {
  it("explains compressed stack stores without scaling the displayed byte offset again", () => {
    const help = explainInstruction(instruction("c.sdsp", "x23,216(x2)"));
    expect(help.title).toBe("Store doubleword · stack-relative");
    expect(help.description).toContain("8 bytes from x23");
    expect(help.description).toContain("x2 (sp, the stack pointer) + 216");
    expect(help.operation).toBe("memory64[x2 + 216] ← x23");
    expect(help.equivalent).toBe("sd x23,216(x2)");
    expect(help.notes.join(" ")).toContain("does not adjust sp");
    expect(help.notes.join(" ")).toContain(
      "16-bit (2-byte) instruction encoding",
    );
  });
  it("distinguishes signed and unsigned loads, word arithmetic, and data widths", () => {
    expect(explainInstruction(instruction("lw", "x10,-4(x8)")).operation).toBe(
      "x10 ← sign_extend64(memory32[x8 - 4])",
    );
    expect(
      explainInstruction(instruction("lwu", "x10,4(x8)")).operation,
    ).toContain("zero_extend64");
    expect(explainInstruction(instruction("ld", "x10,4(x8)")).operation).toBe(
      "x10 ← memory64[x8 + 4]",
    );
    expect(
      explainInstruction(instruction("mulw", "x16,x16,x23")).operation,
    ).toBe("x16 ← sign_extend64(low32(x16 × x23))");
    expect(
      explainInstruction(instruction("c.addi4spn", "x8,x2,48")).equivalent,
    ).toBe("addi x8,x2,48");
  });
  it("handles compressed in-place arithmetic and the two-byte call link correctly", () => {
    expect(explainInstruction(instruction("c.add", "x10,x11")).equivalent).toBe(
      "add x10,x10,x11",
    );
    const help = explainInstruction(instruction("c.jalr", "x8"));
    expect(help.operation).toContain("x1 ← PC + 2");
    expect(help.operation).not.toContain("PC + 4");
    expect(
      explainInstruction(instruction("jalr", "x1,0(x8)")).operation,
    ).toContain("x1 ← PC + 4");
    expect(
      explainInstruction(
        instruction("bne", "x10,x11,80005c94 <symbol>", "2147507348"),
      ).description,
    ).toContain("0x80005c94");
  });
  it("keeps ISA semantics separate from unrecorded runtime values and unknown extensions", () => {
    const help = explainInstruction(instruction("custom.foo", "x1,x2"));
    expect(help.title).toContain("unavailable");
    expect(help.operation).toBeUndefined();
    expect(help.reference).toBeUndefined();
  });
});
describe("assembly token click targets", () => {
  const line =
    "0x80005b22               1  c.sdsp    x23,216(x2) # x8 is a comment";
  it("recognizes every character of a dotted mnemonic", () => {
    const start = line.indexOf("c.sdsp");
    for (let index = start; index < start + 6; index++)
      expect(assemblyTokenAt(line, index + 1)).toEqual({
        kind: "instruction",
        value: "c.sdsp",
      });
  });
  it("keeps register clicks distinct and ignores numbers, whitespace, and comments", () => {
    expect(assemblyTokenAt(line, line.indexOf("x23") + 1)).toEqual({
      kind: "register",
      value: "x23",
    });
    expect(assemblyTokenAt(line, line.indexOf("x2)") + 2)).toEqual({
      kind: "register",
      value: "x2",
    });
    for (const column of [
      1,
      line.indexOf("216") + 1,
      line.indexOf("x8") + 1,
      line.indexOf("c.sdsp"),
    ])
      expect(assemblyTokenAt(line, column)).toBeNull();
    expect(assemblyTokenAt("int x23 = 0;", 6)).toBeNull();
  });
  it("recognizes operand addresses exactly without linking row addresses or comments", () => {
    const text =
      "0x80005cac 19,267,584 bne x27,x14,0x80005c94 # ConvPerChannel + 0x1aa";
    const range = assemblyAddressRange(text, "2147507348")!;
    expect(text.slice(range.start - 1, range.end - 1)).toBe("0x80005c94");
    for (let column = range.start; column < range.end; column++)
      expect(assemblyTokenAt(text, column)).toEqual({
        kind: "address",
        value: "2147507348",
      });
    expect(assemblyAddressRange(text, String(0x80005cac))).toBeNull();
    expect(assemblyAddressRange(text, String(0x1aa))).toBeNull();
    expect(
      assemblyAddressRange(
        "0x100 1 jal x1,0x20000000000003 # target",
        "9007199254740995",
      ),
    ).not.toBeNull();
    expect(assemblyAddressRange(text, "123")).toBeNull();
  });
});
const bundlePath = new URL("../../build/explorer/B0.zip", import.meta.url);
it.skipIf(!existsSync(bundlePath))(
  "real B0: all disassembled mnemonics have readable explanations",
  () => {
    const files = unzipSync(new Uint8Array(readFileSync(bundlePath)), {
      filter: (file) => file.name === "evidence.json",
    });
    const data = JSON.parse(strFromU8(files["evidence.json"])) as Evidence;
    const missing = new Set<string>();
    for (const i of Object.values(data.instructions)) {
      if (!supportedMnemonics.has(i.mnemonic)) missing.add(i.mnemonic);
      const help = explainInstruction(i);
      expect(JSON.stringify(help)).not.toContain("undefined");
    }
    expect([...missing]).toEqual([]);
  },
);
