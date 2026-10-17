import { describe, it, expect } from "vitest";
import { locationsAt } from "./RegisterInspector";
import type { RegisterEvidence } from "./types";
const evidence: RegisterEvidence = {
  schemaVersion: 1,
  elfHash: "test",
  semantics: "before-instruction",
  variables: {},
  coverage: {
    compilationUnits: 1,
    supportedLocations: 3,
    unsupportedExpressions: 0,
    skippedScopes: 0,
  },
  locations: {
    x8: [
      {
        variableId: "a",
        low: "100",
        high: "104",
        kind: "value",
        description: "",
        expression: "DW_OP_reg8",
      },
      {
        variableId: "b",
        low: "104",
        high: "108",
        kind: "value",
        description: "",
        expression: "DW_OP_reg8",
      },
      {
        variableId: "c",
        low: "9007199254740993",
        high: "9007199254740995",
        kind: "address",
        description: "",
        expression: "DW_OP_breg8 0",
      },
    ],
  },
};
describe("register locations at an instruction address", () => {
  it("respects half-open ranges when the compiler reuses a register", () => {
    expect(locationsAt(evidence, "x8", "100").map((l) => l.variableId)).toEqual(
      ["a"],
    );
    expect(locationsAt(evidence, "x8", "104").map((l) => l.variableId)).toEqual(
      ["b"],
    );
    expect(locationsAt(evidence, "x8", "108")).toEqual([]);
  });
  it("preserves exact 64-bit addresses and the distinction between addresses and values", () => {
    expect(locationsAt(evidence, "x8", "9007199254740993")[0].kind).toBe(
      "address",
    );
    expect(locationsAt(evidence, "x8", "9007199254740995")).toEqual([]);
  });
  it("supports older bundles and registers without available mappings", () => {
    expect(locationsAt(undefined, "x8", "100")).toEqual([]);
    expect(locationsAt(evidence, "x9", "100")).toEqual([]);
  });
});
