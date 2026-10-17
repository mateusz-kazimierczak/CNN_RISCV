import type { Instruction } from "./types";

const manual = "https://docs.riscv.org/reference/isa/v20240411/";
const sources = {
  I: manual + "unpriv/rv32.html",
  RV64: manual + "unpriv/rv64.html",
  C: manual + "unpriv/c-st-ext.html",
  M: manual + "unpriv/m-st-ext.html",
  privileged: manual + "priv/machine.html",
};
export interface InstructionHelp {
  title: string;
  description: string;
  operation?: string;
  equivalent?: string;
  notes: string[];
  reference?: string;
}
export const supportedMnemonics = new Set<string>();
type Explain = (
  operands: string[],
  instruction: Instruction,
) => InstructionHelp;
const explanations = new Map<string, Explain>();
function define(names: string, explain: Explain) {
  for (const name of names.split(" ")) {
    explanations.set(name, explain);
    supportedMnemonics.add(name);
  }
}
const wordNote =
  "The low 32 result bits are sign-extended to 64 bits, even for unsigned word operations.";
const target = (instruction: Instruction, operand: string) =>
  instruction.transfer.target
    ? "0x" + BigInt(instruction.transfer.target).toString(16)
    : operand?.split(" ")[0];
const memoryAddress = (operand: string) => {
  const match = /^(-?(?:0x[0-9a-f]+|\d+))\((x\d+)\)$/.exec(operand);
  return match
    ? `${match[2]} ${match[1].startsWith("-") ? "- " + match[1].slice(1) : "+ " + match[1]}`
    : operand;
};

for (const [name, bits, signed] of [
  ["lb", 8, true],
  ["lbu", 8, false],
  ["lh", 16, true],
  ["lhu", 16, false],
  ["lw", 32, true],
  ["lwu", 32, false],
  ["ld", 64, false],
] as const)
  define(name, ([rd, address]) => ({
    title: `Load ${bits === 8 ? "byte" : bits === 16 ? "halfword" : bits === 32 ? "word" : "doubleword"}${bits < 64 && !signed ? " unsigned" : ""}`,
    description: `Read ${bits / 8} ${bits === 8 ? "byte" : "bytes"} from memory at ${memoryAddress(address)} into ${rd}.`,
    operation: `${rd} ← ${bits < 64 ? (signed ? "sign_extend64" : "zero_extend64") + "(" : ""}memory${bits}[${memoryAddress(address)}]${bits < 64 ? ")" : ""}`,
    notes:
      bits < 64
        ? [
            `${signed ? "Sign" : "Zero"}-extend the loaded ${bits}-bit value to 64 bits.`,
          ]
        : [],
    reference: bits >= 32 ? sources.RV64 : sources.I,
  }));
for (const [name, bits] of [
  ["sb", 8],
  ["sh", 16],
  ["sw", 32],
  ["sd", 64],
] as const)
  define(name, ([rs, address]) => ({
    title: `Store ${bits === 8 ? "byte" : bits === 16 ? "halfword" : bits === 32 ? "word" : "doubleword"}`,
    description: `Write ${bits / 8} ${bits === 8 ? "byte" : "bytes"} from ${rs} to memory at ${memoryAddress(address)}.`,
    operation: `memory${bits}[${memoryAddress(address)}] ← ${bits < 64 ? "low" + bits + "(" + rs + ")" : rs}`,
    notes: ["The source register and address base register are unchanged."],
    reference: name === "sd" ? sources.RV64 : sources.I,
  }));

for (const [name, title, symbol] of [
  ["add", "Add", "+"],
  ["sub", "Subtract", "-"],
  ["and", "Bitwise AND", "&"],
  ["or", "Bitwise OR", "|"],
  ["xor", "Bitwise XOR", "^"],
] as const) {
  for (const suffix of name === "add" || name === "sub" ? ["", "w"] : [""])
    define(name + suffix, ([rd, a, b]) => ({
      title: `${title}${suffix ? " word" : ""}`,
      description: `Compute ${a} ${symbol} ${b} and write the ${suffix ? "32" : "64"}-bit result to ${rd}.`,
      operation: `${rd} ← ${suffix ? "sign_extend64(low32(" : "low64("}${a} ${symbol} ${b}${suffix ? "))" : ")"}`,
      notes: suffix
        ? [wordNote]
        : ["Only the low 64 result bits are retained."],
      reference: suffix ? sources.RV64 : sources.I,
    }));
}
for (const [name, symbol] of [
  ["addi", "+"],
  ["andi", "&"],
  ["ori", "|"],
  ["xori", "^"],
] as const)
  define(name, ([rd, a, imm]) => ({
    title: {
      addi: "Add immediate",
      andi: "Bitwise AND immediate",
      ori: "Bitwise OR immediate",
      xori: "Bitwise XOR immediate",
    }[name],
    description: `Combine ${a} with the constant ${imm}, then write the result to ${rd}.`,
    operation: `${rd} ← low64(${a} ${symbol} ${imm})`,
    notes: [
      "The encoded 12-bit immediate is sign-extended before the operation.",
    ],
    reference: sources.I,
  }));
define("addiw", ([rd, a, imm]) => ({
  title: "Add immediate word",
  description: `Add ${imm} to ${a}, keeping a signed 32-bit result in ${rd}.`,
  operation: `${rd} ← sign_extend64(low32(${a} + ${imm}))`,
  notes: [wordNote],
  reference: sources.RV64,
}));
for (const name of [
  "sll",
  "slli",
  "sllw",
  "slliw",
  "srl",
  "srli",
  "srlw",
  "srliw",
  "sra",
  "srai",
  "sraw",
  "sraiw",
])
  define(name, ([rd, a, b]) => {
    const word = name.endsWith("w"),
      immediate = name.includes("i"),
      width = word ? 32 : 64;
    const left = name.startsWith("sll"),
      arithmetic = name.startsWith("sra");
    return {
      title: `${arithmetic ? "Arithmetic" : "Logical"} shift ${left ? "left" : "right"}${word ? " word" : ""}${immediate ? " immediate" : ""}`,
      description: `Shift ${a} ${left ? "left" : "right"} by ${immediate ? b : "the low " + (word ? 5 : 6) + " bits of " + b} bit positions into ${rd}.`,
      operation: `${rd} ← ${word ? "sign_extend64(" : ""}${left ? "shift_left" : arithmetic ? "signed_shift_right" : "zero_fill_shift_right"}${width}(${a}, ${b}${immediate ? "" : " & " + (width - 1)})${word ? ")" : ""}`,
      notes: [
        arithmetic
          ? "The sign bit fills the vacated high bits."
          : "Vacated bit positions are filled with zeros.",
        ...(word ? [wordNote] : []),
      ],
      reference: word ? sources.RV64 : sources.I,
    };
  });
for (const name of ["slt", "sltu", "slti", "sltiu"])
  define(name, ([rd, a, b]) => ({
    title: `Set if less than${name.endsWith("u") ? " unsigned" : ""}${name.includes("i") ? " immediate" : ""}`,
    description: `Set ${rd} to 1 if ${a} is less than ${b}; otherwise set it to 0.`,
    operation: `${rd} ← ${name.endsWith("u") ? "unsigned" : "signed"}(${a}) < ${name.endsWith("u") ? "unsigned" : "signed"}(${b}) ? 1 : 0`,
    notes: name.includes("i")
      ? [
          "The immediate is sign-extended first, including for the unsigned comparison.",
        ]
      : [],
    reference: sources.I,
  }));
for (const [name, relation, signed] of [
  ["beq", "==", ""],
  ["bne", "!=", ""],
  ["blt", "<", "signed"],
  ["bge", ">=", "signed"],
  ["bltu", "<", "unsigned"],
  ["bgeu", ">=", "unsigned"],
] as const)
  define(name, ([a, b, address], instruction) => ({
    title: `Branch if ${name.startsWith("beq") ? "equal" : name.startsWith("bne") ? "not equal" : name.startsWith("blt") ? "less than" : "greater than or equal"}${signed === "unsigned" ? " unsigned" : ""}`,
    description: `Jump to ${target(instruction, address)} when ${a} ${relation} ${b}${signed ? " using a " + signed + " comparison" : ""}; otherwise continue with the next instruction.`,
    operation: `if (${a} ${relation}${signed ? " [" + signed + "]" : ""} ${b}) PC ← ${target(instruction, address)}`,
    notes: [
      "The target is static; PC counts do not tell us whether a particular branch was taken.",
    ],
    reference: sources.I,
  }));
define("lui", ([rd, imm]) => ({
  title: "Load upper immediate",
  description: `Place the immediate ${imm} in bits 31:12 of ${rd}, with the low 12 bits zero.`,
  operation: `${rd} ← sign_extend64(${imm} << 12)`,
  notes: ["The 32-bit constructed value is sign-extended to 64 bits."],
  reference: sources.RV64,
}));
define("auipc", ([rd, imm], instruction) => ({
  title: "Add upper immediate to PC",
  description: `Build a PC-relative value in ${rd} using this instruction's address.`,
  operation: `${rd} ← low64(0x${BigInt(instruction.pc).toString(16)} + sign_extend64(${imm} << 12))`,
  notes: ["The immediate forms a signed 32-bit offset with 12 low zero bits."],
  reference: sources.RV64,
}));
define("jal", ([rd, address], instruction) => ({
  title: "Jump and link",
  description: `Jump to ${target(instruction, address)} and write the next instruction's address to ${rd}.`,
  operation: `${rd} ← PC + 4; PC ← ${target(instruction, address)}`,
  notes: [
    rd === "x0"
      ? "Writes to x0 are discarded: this is an unconditional jump without a saved return address."
      : "x1 (ra) is the usual return-address register for calls.",
  ],
  reference: sources.I,
}));
define("jalr", ([rd, address]) => ({
  title: "Jump and link register",
  description: `Jump to the address computed from ${address}, clearing its lowest bit; save the following instruction's address in ${rd}.`,
  operation: `target ← (${memoryAddress(address)}) & ~1; ${rd} ← PC + 4; PC ← target`,
  notes: [
    "The target is computed before writing the destination. x0 discards the link value.",
  ],
  reference: sources.I,
}));
for (const name of ["mul", "mulw", "mulh", "mulhu", "mulhsu"])
  define(name, ([rd, a, b]) => {
    const word = name === "mulw",
      high = name.startsWith("mulh");
    return {
      title: `Multiply${word ? " word" : high ? " high half" : ""}`,
      description: `Multiply ${a} by ${b}, placing the ${word ? "low 32 bits" : high ? "upper 64 bits of the 128-bit product" : "low 64 bits"} in ${rd}.`,
      operation: `${rd} ← ${word ? "sign_extend64(low32" : high ? "high64" : "low64"}(${a} × ${b})${word ? ")" : ""}`,
      notes: word
        ? [wordNote]
        : high
          ? [
              name === "mulhu"
                ? "Both operands are unsigned."
                : name === "mulhsu"
                  ? "The first operand is signed; the second is unsigned."
                  : "Both operands are signed.",
            ]
          : [
              "For the low half, signed and unsigned multiplication give the same result bits.",
            ],
      reference: sources.M,
    };
  });
for (const name of [
  "div",
  "divu",
  "divw",
  "divuw",
  "rem",
  "remu",
  "remw",
  "remuw",
])
  define(name, ([rd, a, b]) => {
    const remainder = name.startsWith("rem"),
      word = name.endsWith("w"),
      unsigned = name.includes("u");
    return {
      title: `${unsigned ? "Unsigned" : "Signed"} ${remainder ? "remainder" : "division"}${word ? " word" : ""}`,
      description: `Compute the ${remainder ? "remainder" : "quotient"} of ${a} divided by ${b}, using ${word ? 32 : 64}-bit ${unsigned ? "unsigned" : "signed"} operands.`,
      operation: `${rd} ← ${word ? "sign_extend64(" : ""}${unsigned ? "unsigned" : "signed"}_${remainder ? "remainder" : "quotient"}${word ? "32" : "64"}(${a}, ${b})${word ? ")" : ""}`,
      notes: [
        "Signed division rounds toward zero; a signed remainder has the dividend's sign.",
        "Division by zero yields an all-ones quotient and the dividend as remainder. Signed overflow yields the dividend as quotient and zero remainder.",
        ...(word ? [wordNote] : []),
      ],
      reference: sources.M,
    };
  });

// Expansion describes behavior; a compressed link uses PC+2, never PC+4.
const compressed: Record<string, (p: string[]) => [string, string[]]> = {};
for (const op of ["lw", "ld", "sw", "sd"])
  for (const suffix of ["", "sp"])
    compressed[`c.${op}${suffix}`] = (p) => [op, p];
for (const op of ["add", "addw", "sub", "subw", "and", "or", "xor"])
  compressed[`c.${op}`] = ([rd, rs]) => [op, [rd, rd, rs]];
for (const op of ["addi", "addiw", "andi", "slli", "srli", "srai"])
  compressed[`c.${op}`] = ([rd, imm]) => [op, [rd, rd, imm]];
compressed["c.mv"] = ([rd, rs]) => ["add", [rd, "x0", rs]];
compressed["c.li"] = ([rd, imm]) => ["addi", [rd, "x0", imm]];
compressed["c.lui"] = (p) => ["lui", p];
compressed["c.addi16sp"] = ([rd, imm]) => ["addi", [rd, rd, imm]];
compressed["c.addi4spn"] = (p) => ["addi", p];
compressed["c.beqz"] = ([rs, address]) => ["beq", [rs, "x0", address]];
compressed["c.bnez"] = ([rs, address]) => ["bne", [rs, "x0", address]];
compressed["c.j"] = ([address]) => ["jal", ["x0", address]];
compressed["c.jr"] = ([rs]) => ["jalr", ["x0", `0(${rs})`]];
compressed["c.jalr"] = ([rs]) => ["jalr", ["x1", `0(${rs})`]];
for (const [name, expand] of Object.entries(compressed))
  define(name, (p, instruction) => {
    const [base, operands] = expand(p);
    const help = explanations.get(base)!(operands, instruction);
    const stack =
      name.endsWith("sp") &&
      ["c.sdsp", "c.swsp", "c.ldsp", "c.lwsp"].includes(name);
    const link = name === "c.jalr";
    return {
      ...help,
      title:
        (
          {
            "c.mv": "Move register",
            "c.li": "Load immediate",
            "c.addi16sp": "Adjust stack pointer",
            "c.addi4spn": "Form stack-relative address",
          } as Record<string, string>
        )[name] || `${help.title}${stack ? " · stack-relative" : ""}`,
      description: stack
        ? help.description.replace(/\bx2\b/g, "x2 (sp, the stack pointer)")
        : help.description,
      operation: link
        ? help.operation?.replace("PC + 4", "PC + 2")
        : help.operation,
      equivalent: `${base} ${operands.join(",")}${link ? " (link address is PC + 2)" : ""}`,
      notes: [
        "c. means a 16-bit (2-byte) instruction encoding; it does not mean 16-bit data.",
        ...(stack
          ? [
              "x2 is sp, the stack pointer. The displayed offset is already in bytes; the instruction does not adjust sp.",
            ]
          : []),
        // Expanded ADDI/ANDI semantics apply, but their 12-bit encoding note
        // describes the uncompressed instruction rather than this encoding.
        ...help.notes.filter(
          (note) => !note.includes("encoded 12-bit immediate"),
        ),
      ],
      reference: sources.C,
    };
  });
define("wfi", () => ({
  title: "Wait for interrupt",
  description:
    "Notify the implementation that this hart may wait for an interrupt before continuing.",
  notes: [
    "An implementation may treat this as a no-op; privilege and trap settings affect its behavior.",
  ],
  reference: sources.privileged,
}));
define("nop c.nop", () => ({
  title: "No operation",
  description:
    "Continue to the next instruction without changing integer register state.",
  notes: [],
  reference: sources.I,
}));

export function explainInstruction(instruction: Instruction): InstructionHelp {
  const explain = explanations.get(instruction.mnemonic);
  if (!explain)
    return {
      title: "Instruction reference unavailable",
      description:
        "This instruction is outside the viewer's RV64 instruction reference. No semantics are inferred from its name.",
      notes: [],
    };
  const operands = instruction.operands
    .split("#")[0]
    .split(",")
    .map((operand) => operand.trim());
  return explain(operands, instruction);
}
