import { describe, it, expect } from "vitest";
import { zipSync, strToU8, strFromU8 } from "fflate";
import { existsSync, readFileSync } from "node:fs";
import { readBundle, safePath, LIMITS } from "./bundle";
import type { Evidence } from "./types";
import { sum, exact } from "./types";

function fixture(): Evidence {
  const large = "9007199254740993";
  return {
    schemaVersion: 1,
    provenance: {
      configuration: "fixture",
      compiler: "test",
      input_seed: 1,
      output_fnv1a: "test",
      hashes: { profile_elf: "hash" },
      sourceSnapshotStatus: "test",
      boundaries: "test",
    },
    graph: {
      nodes: [
        {
          id: "0",
          index: 0,
          type: "TEST",
          group: "TEST",
          inputs: [0],
          outputs: [1],
          eventId: "2",
          input_shapes: [[1]],
          output_shapes: [[1]],
          logical_macs: "1",
          executed_products: "1",
          options: {},
        },
      ],
      tensors: [
        {
          id: 0,
          name: "in",
          shape: [1],
          type: "INT8",
          constant: false,
          quantization: null,
          producer: null,
          consumers: ["0"],
        },
        {
          id: 1,
          name: "out",
          shape: [1],
          type: "INT8",
          constant: false,
          quantization: null,
          producer: "0",
          consumers: [],
        },
      ],
      edges: [],
      inputs: [0],
      outputs: [1],
    },
    events: [
      {
        id: "0",
        name: "allocate",
        kind: "region",
        nodeId: null,
        total: "1",
        counts: { "128": "1" },
        mix: {},
      },
      {
        id: "1",
        name: "invoke",
        kind: "region",
        nodeId: null,
        total: large,
        counts: { "128": large },
        mix: {},
      },
      {
        id: "2",
        name: "TEST",
        kind: "operator",
        nodeId: "0",
        total: large,
        counts: { "128": large },
        mix: {},
      },
      {
        id: "overhead",
        name: "overhead",
        kind: "derived",
        nodeId: null,
        total: "0",
        counts: {},
        mix: {},
      },
    ],
    instructions: {
      "128": {
        pc: "128",
        bits: "0x1",
        length: 2,
        mnemonic: "c.nop",
        operands: "",
        category: "integer_alu",
        functionIds: ["f"],
        functionId: "f",
        frames: [],
        transfer: { kind: "next", target: null },
      },
    },
    functions: [
      {
        id: "f",
        name: "test",
        aliases: [],
        linkageNames: [],
        address: "128",
        size: 2,
        pcs: ["128"],
        cfg: {
          blocks: [
            { id: "b", start: "128", pcs: ["128"], successors: [], calls: [] },
          ],
          loops: [],
          complete: true,
          unresolved: [],
        },
      },
    ],
    sources: {},
    annotations: [],
    compilerUnits: [],
    totals: { inference: large, allocation: "1", overhead: "0" },
    capabilities: {
      compiler: false,
      loops: true,
      sourceMappedInstructions: 0,
      staticInstructions: 1,
    },
  };
}
async function pack(data: Evidence) {
  const content = strToU8(JSON.stringify(data));
  const digest = Buffer.from(
    await crypto.subtle.digest("SHA-256", content),
  ).toString("hex");
  return zipSync({
    "manifest.json": strToU8(
      JSON.stringify({
        format: "riscv-execution-explorer",
        schemaVersion: 1,
        files: { "evidence.json": { size: content.length, sha256: digest } },
      }),
    ),
    "evidence.json": content,
  });
}
describe("portable evidence import", () => {
  it("validates symbolic relationships and rejects invalid memory operations and references", async () => {
    const d = fixture();
    d.registers = {
      schemaVersion: 1,
      elfHash: "hash",
      semantics: "before-instruction",
      variables: {
        v: {
          id: "v",
          name: "value",
          type: "int",
          function: "kernel",
          kind: "local",
          declaration: null,
        },
      },
      locations: {},
      relations: {
        x14: [
          {
            variableId: "v",
            low: "128",
            high: "130",
            offset: "-1",
            bytes: 1,
            signed: true,
            expression: "DWARF",
          },
        ],
      },
      coverage: {
        compilationUnits: 1,
        supportedLocations: 0,
        unsupportedExpressions: 0,
        skippedScopes: 0,
      },
    };
    expect(
      (await readBundle(await pack(d))).evidence.registers?.relations?.x14[0]
        .offset,
    ).toBe("-1");
    d.registers.relations!.x14[0].bytes = 128;
    await expect(readBundle(await pack(d))).rejects.toThrow("symbolic memory");
    d.registers.relations!.x14[0].bytes = 1;
    d.registers.relations!.x14[0].variableId = "missing";
    await expect(readBundle(await pack(d))).rejects.toThrow(
      "relation range/reference",
    );
    d.registers.relations!.x14[0].variableId = "v";
    d.registers.compilerOrigins = {
      "128": {
        x14: [
          {
            name: "temp",
            unitId: "missing",
            artifactPath: "rtl",
            startLine: 1,
            endLine: 2,
            assemblyPath: "asm",
            assemblyLine: 1,
            matching: "unique-loop-window",
            loopId: "missing",
          },
        ],
      },
    };
    await expect(readBundle(await pack(d))).rejects.toThrow(
      "Unverified compiler register origins",
    );
    delete d.registers.compilerOrigins;
    d.registers.roles = [
      {
        register: "x14",
        functionId: "missing",
        loopId: "missing",
        kind: "pointer",
        pcs: ["128"],
        stride: 1,
        loadPcs: ["128"],
        updatePcs: [],
        comparePc: "128",
        sourceVariableIds: ["v"],
      },
    ];
    await expect(readBundle(await pack(d))).rejects.toThrow("loop role");
  });
  it("validates optional register mappings and rejects mismatched ELF/range references", async () => {
    const d = fixture();
    d.registers = {
      schemaVersion: 1,
      elfHash: "hash",
      semantics: "before-instruction",
      variables: {
        v: {
          id: "v",
          name: "acc",
          type: "int",
          function: "kernel",
          kind: "local",
          declaration: null,
        },
      },
      locations: {
        x8: [
          {
            variableId: "v",
            low: "128",
            high: "130",
            kind: "value",
            description: "value",
            expression: "DW_OP_reg8",
          },
        ],
      },
      coverage: {
        compilationUnits: 1,
        supportedLocations: 1,
        unsupportedExpressions: 0,
        skippedScopes: 0,
      },
    };
    expect(
      (await readBundle(await pack(d))).evidence.registers?.variables.v.name,
    ).toBe("acc");
    d.registers.elfHash = "different";
    await expect(readBundle(await pack(d))).rejects.toThrow("identity");
    d.registers.elfHash = "hash";
    d.registers.locations.x8[0].high = "128";
    await expect(readBundle(await pack(d))).rejects.toThrow("range");
  });
  it("preserves >53-bit counters and keeps static instructions shared", async () => {
    const { evidence: d } = await readBundle(await pack(fixture()));
    expect(sum(["128"], d.events[2].counts)).toBe(9007199254740993n);
    expect(exact(d.events[2].total)).toBe("9,007,199,254,740,993");
    expect(Object.keys(d.instructions)).toHaveLength(1);
  });
  it("rejects malformed schema, references, totals and negative/overflowing counts", async () => {
    const modifications = [
      (d: Evidence) => {
        d.schemaVersion = 2;
      },
      (d: Evidence) => {
        d.events[2].counts = { "999": "9007199254740993" };
      },
      (d: Evidence) => {
        d.events[2].total = "8";
      },
      (d: Evidence) => {
        d.events[2].counts["128"] = "-1";
      },
      (d: Evidence) => {
        d.events[2].counts["128"] = "18446744073709551616";
      },
      (d: Evidence) => {
        d.graph.nodes[0].eventId = "0";
      },
      (d: Evidence) => {
        d.functions[0].cfg.blocks[0].successors = [
          { to: "missing", kind: "branch" },
        ];
      },
    ];
    for (const modify of modifications) {
      const d = fixture();
      modify(d);
      await expect(readBundle(await pack(d))).rejects.toThrow();
    }
  });
  it("rejects per-PC attribution changes even when event totals match", async () => {
    const d = fixture();
    d.instructions["130"] = { ...d.instructions["128"], pc: "130" };
    d.events[2].counts = { "130": d.events[2].total };
    await expect(readBundle(await pack(d))).rejects.toThrow("per PC");
  });
  it("disables annotations whose ELF or source hashes are stale", async () => {
    const d = fixture();
    d.annotations = [
      {
        id: "a",
        title: "stale",
        category: "address",
        description: "",
        pcs: ["128"],
        elfHash: "wrong",
        sourceHashes: {},
        evidence: "fixture",
        status: "reviewed",
      },
    ];
    expect(
      (await readBundle(await pack(d))).evidence.annotations[0].status,
    ).toBe("stale");
  });
  it("rejects unsafe paths and duplicate ZIP entries", async () => {
    for (const name of ["../bad", "/bad", "C:/bad", "a\\b", "a/./b", "a//b"]) {
      expect(safePath(name)).toBe(false);
      await expect(
        readBundle(zipSync({ [name]: strToU8("bad") })),
      ).rejects.toThrow("path");
    }
    const zip = zipSync({ "a.txt": strToU8("a"), "b.txt": strToU8("b") });
    const copy = zip.slice();
    for (let i = 0; i < copy.length - 5; i++)
      if (strFromU8(copy.subarray(i, i + 5)) === "b.txt") copy[i] = 97;
    await expect(readBundle(copy)).rejects.toThrow("Duplicate");
  });
  it("enforces decompressed limits while reading", async () => {
    const original = LIMITS.entry;
    try {
      LIMITS.entry = 1024;
      await expect(
        readBundle(zipSync({ "large.txt": new Uint8Array(4096) })),
      ).rejects.toThrow("limit");
    } finally {
      LIMITS.entry = original;
    }
  });
  it("rejects corruption and unlisted entries", async () => {
    const data = fixture();
    const bytes = await pack(data);
    const { unzipSync } = await import("fflate");
    const files = unzipSync(bytes);
    files["evidence.json"][20] ^= 1;
    await expect(readBundle(zipSync(files))).rejects.toThrow("integrity");
    files["extra.txt"] = strToU8("extra");
    await expect(readBundle(zipSync(files))).rejects.toThrow("Unlisted");
  });
  it.skipIf(!existsSync("../build/explorer/B0.zip"))(
    "loads real B0 and verified compiler function indexes",
    async () => {
      const { evidence: d } = await readBundle(
        new Uint8Array(readFileSync("../build/explorer/B0.zip")),
      );
      expect(d.events.find((e) => e.nodeId === "4")?.total).toBe("327839821");
      expect(d.graph.nodes).toHaveLength(64);
      expect(d.totals.inference).toBe("4867278370");
      expect(
        d.graph.edges.some(
          (e) => d.graph.nodes.find((n) => n.id === e.target)?.type === "ADD",
        ),
      ).toBe(true);
      if (d.compilerUnits.length) expect(d.compilerUnits).toHaveLength(4);
    },
    30000,
  );
});
