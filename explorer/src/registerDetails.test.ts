import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { unzipSync, strFromU8 } from "fflate";
import type { Evidence, RegisterRelation } from "./types";
import { registerDetails, memoryRelationText } from "./registerDetails";
const relation: RegisterRelation = {
  variableId: "v",
  low: "100",
  high: "108",
  offset: "-1",
  bytes: 1,
  signed: true,
  expression: "DWARF",
};
describe("symbolic source relationships", () => {
  it("formats memory reads without pretending to know pointer values or memory contents", () => {
    expect(memoryRelationText("x14", relation)).toBe("signed_byte_at(x14 - 1)");
    expect(
      memoryRelationText("x17", {
        ...relation,
        offset: "0",
        signed: false,
        bytes: 4,
      }),
    ).toBe("load32(x17)");
    expect(
      memoryRelationText("x17", {
        ...relation,
        offset: "9007199254740993",
        signed: false,
        bytes: 8,
      }),
    ).toBe("load64(x17 + 9007199254740993)");
  });
});
const bundlePath = new URL("../../build/explorer/B0.zip", import.meta.url);
describe.skipIf(!existsSync(bundlePath))("real B0 register provenance", () => {
  const read = () => {
    const files = unzipSync(new Uint8Array(readFileSync(bundlePath)), {
      filter: (f) => f.name === "evidence.json",
    });
    return JSON.parse(strFromU8(files["evidence.json"])) as Evidence;
  };
  it("distinguishes an active relationship from one whose lexical scope ends at the branch", () => {
    const data = read();
    const active = registerDetails(data, "x14", String(0x80005ca8), "4");
    expect(active.relations.some((r) => r.offset === "-1" && r.signed)).toBe(
      true,
    );
    const branch = registerDetails(data, "x14", String(0x80005cac), "4");
    expect(branch.relations).toEqual([]);
    expect(branch.nearbyRelations[0].high).toBe(String(0x80005cac));
    expect(branch.role?.kind).toBe("pointer");
    expect(branch.role?.stride).toBe(1);
    expect(branch.variables.some((v) => v.name === "filter_val")).toBe(true);
    expect(branch.origins[0].name).toBe("ivtmp.85");
  });
  it("shows layer-specific spans with source evidence and keeps whole-inference values unavailable", () => {
    const data = read();
    const end = registerDetails(data, "x27", String(0x80005cac), "4");
    expect(end.role?.kind).toBe("boundary");
    expect(end.role?.span?.source?.name).toBe("filter_input_depth");
    expect(end.span?.value).toBe("16");
    expect(end.origins[0].name).toBe("_90");
    expect(
      registerDetails(data, "x27", String(0x80005cac), "9").span?.value,
    ).toBe("144");
    expect(
      registerDetails(data, "x27", String(0x80005cac), null).span?.value,
    ).toBeUndefined();
  });
  it("retains local instruction uses for legacy bundles, and ignores stale register metadata", () => {
    const data = read();
    data.registers!.elfHash = "stale";
    const stale = registerDetails(data, "x14", String(0x80005cac), "4");
    expect(stale.role).toBeUndefined();
    expect(stale.origins).toEqual([]);
    expect(stale.uses).toContain(String(0x80005c98));
    delete data.registers;
    expect(
      registerDetails(data, "x14", String(0x80005cac), "4").uses,
    ).toContain(String(0x80005c9c));
  });
});
