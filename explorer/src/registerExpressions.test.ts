import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { unzipSync, strFromU8 } from "fflate";
import {
  inferRegisterExpression,
  type RegisterAnalysis,
} from "./registerExpressions";
import type { Evidence, Instruction } from "./types";

function fixture(rows: [string, string][]): RegisterAnalysis {
  const instructions = Object.fromEntries(
    rows.map(([mnemonic, operands], index) => {
      const pc = String(100 + 4 * index);
      return [
        pc,
        {
          pc,
          mnemonic,
          operands,
          length: 4,
          transfer: { kind: "next", target: null },
        } as Instruction,
      ];
    }),
  );
  return {
    instructions,
    functions: [
      {
        id: "f",
        name: "f",
        aliases: [],
        linkageNames: [],
        size: rows.length * 4,
        address: "100",
        pcs: Object.keys(instructions),
        cfg: {
          complete: true,
          unresolved: [],
          loops: [],
          blocks: [
            {
              id: "b",
              start: "100",
              pcs: Object.keys(instructions),
              successors: [],
              calls: [],
            },
          ],
        },
      },
    ],
    registers: {
      schemaVersion: 1,
      elfHash: "test",
      semantics: "before-instruction",
      coverage: {
        compilationUnits: 1,
        supportedLocations: 2,
        unsupportedExpressions: 0,
        skippedScopes: 0,
      },
      variables: {
        input: {
          id: "input",
          name: "input_val",
          type: "int32_t",
          function: "f",
          kind: "local",
          declaration: null,
        },
        offset: {
          id: "offset",
          name: "input_offset",
          type: "int32_t",
          function: "f",
          kind: "local",
          declaration: null,
        },
        filter: {
          id: "filter",
          name: "filter_val",
          type: "int32_t",
          function: "f",
          kind: "local",
          declaration: null,
        },
      },
      locations: {
        x23: [
          {
            variableId: "input",
            low: "104",
            high: "108",
            kind: "value",
            description: "",
            expression: "",
          },
        ],
        x16: [
          {
            variableId: "offset",
            low: "100",
            high: "104",
            kind: "value",
            description: "",
            expression: "",
          },
        ],
      },
    },
  };
}
const rows: [string, string][] = [
  ["c.mv", "x8,x16"],
  ["addw", "x23,x23,x8"],
  ["mulw", "x16,x16,x23"],
];

describe("static register expressions", () => {
  it("traces copies and describes state before the selected instruction", () => {
    const data = fixture(rows);
    expect(inferRegisterExpression(data, "x23", "104")?.text).toBe("input_val");
    const result = inferRegisterExpression(data, "x23", "108");
    expect(result?.text).toBe("input_val + input_offset");
    expect(result?.word32).toBe(true);
    expect(result?.steps.map((step) => step.pc)).toEqual([
      "104",
      "100",
      "100",
      "104",
    ]);
  });
  it("keeps precedence for a product of an adjusted input", () => {
    const data = fixture([...rows, ["nop", ""]]);
    data.registers!.locations.x16.push({
      variableId: "filter",
      low: "108",
      high: "112",
      kind: "value",
      description: "",
      expression: "",
    });
    expect(inferRegisterExpression(data, "x16", "112")?.text).toBe(
      "filter_val * (input_val + input_offset)",
    );
  });
  it("does not propagate through a load, unsupported transform, or custom side effects", () => {
    for (const instruction of [
      ["lw", "x23,0(x8)"],
      ["slliw", "x23,x23,2"],
      ["custom", "x9,x8"],
    ] as [string, string][]) {
      const data = fixture([rows[0], instruction, ["nop", ""]]);
      data.registers!.locations.x23 = [];
      expect(inferRegisterExpression(data, "x23", "108")).toBeNull();
    }
  });
  it("distinguishes named values from address/piece metadata and ambiguity", () => {
    for (const kind of ["address", "piece"] as const) {
      const data = fixture(rows);
      data.registers!.locations.x23[0].kind = kind;
      expect(inferRegisterExpression(data, "x23", "108")).toBeNull();
    }
    const data = fixture(rows);
    data.registers!.locations.x23.push({
      ...data.registers!.locations.x23[0],
      variableId: "filter",
    });
    expect(inferRegisterExpression(data, "x23", "108")).toBeNull();
  });
  it("preserves callee-saved copies but invalidates caller-saved values across calls", () => {
    const data = fixture([rows[0], ["jal", "x1,1000"], ["nop", ""]]);
    data.instructions["104"].transfer.kind = "call";
    expect(inferRegisterExpression(data, "x8", "108")?.text).toBe(
      "input_offset",
    );
    expect(inferRegisterExpression(data, "x16", "108")).toBeNull();
  });
  it("requires all incoming paths to agree and traverses unchanged loop backedges", () => {
    const data = fixture([rows[0], ["nop", ""], ["nop", ""], ["nop", ""]]);
    const fn = data.functions[0];
    fn.cfg.blocks = [
      {
        id: "entry",
        start: "100",
        pcs: ["100"],
        successors: [
          { to: "left", kind: "branch" },
          { to: "right", kind: "fallthrough" },
        ],
        calls: [],
      },
      {
        id: "left",
        start: "104",
        pcs: ["104"],
        successors: [{ to: "join", kind: "jump" }],
        calls: [],
      },
      {
        id: "right",
        start: "108",
        pcs: ["108"],
        successors: [{ to: "join", kind: "jump" }],
        calls: [],
      },
      {
        id: "join",
        start: "112",
        pcs: ["112"],
        successors: [{ to: "join", kind: "branch" }],
        calls: [],
      },
    ];
    expect(inferRegisterExpression(data, "x8", "112")?.text).toBe(
      "input_offset",
    );
    data.instructions["108"].mnemonic = "c.li";
    data.instructions["108"].operands = "x8,1";
    expect(inferRegisterExpression(data, "x8", "112")).toBeNull();
    data.instructions["108"].mnemonic = "ld";
    data.instructions["108"].operands = "x8,0(x2)";
    expect(inferRegisterExpression(data, "x8", "112")).toBeNull();
  });
  it("rejects value-changing recurrence and incomplete control flow", () => {
    const data = fixture([
      ["nop", ""],
      ["c.addi", "x8,1"],
      ["nop", ""],
    ]);
    data.functions[0].cfg.blocks[0].successors = [{ to: "b", kind: "branch" }];
    expect(inferRegisterExpression(data, "x8", "108")).toBeNull();
    data.functions[0].cfg.complete = false;
    expect(inferRegisterExpression(data, "x23", "104")).toBeNull();
  });
  it("supports legacy bundles without fabricating variable expressions", () => {
    const data = fixture(rows);
    delete data.registers;
    expect(inferRegisterExpression(data, "x23", "108")).toBeNull();
  });
});

const bundlePath = new URL("../../build/explorer/B0.zip", import.meta.url);
it.skipIf(!existsSync(bundlePath))(
  "real B0: x23 at line 158 is the adjusted input, x8 is the copied offset",
  () => {
    const files = unzipSync(new Uint8Array(readFileSync(bundlePath)), {
      filter: (file) => file.name === "evidence.json",
    });
    const data = JSON.parse(strFromU8(files["evidence.json"])) as Evidence;
    expect(inferRegisterExpression(data, "x23", String(0x80005ca2))?.text).toBe(
      "input_val + input_offset",
    );
    expect(inferRegisterExpression(data, "x8", String(0x80005c9e))?.text).toBe(
      "input_offset",
    );
  },
);
