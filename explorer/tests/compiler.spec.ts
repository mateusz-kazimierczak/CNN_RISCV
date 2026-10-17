import { test, expect } from "@playwright/test";
import { existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { zipSync, strToU8 } from "fflate";
import type { Evidence } from "../src/types";

test("real A0 graph, compiler-known parameters, memory plan and verified GCC", async ({
  page,
}) => {
  test.skip(
    !existsSync("../build/explorer/A0.zip"),
    "Export compiler evidence first",
  );
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page
    .getByLabel("Open profile bundle")
    .setInputFiles("../build/explorer/A0.zip");
  await expect(page.getByLabel("Execution scope")).toHaveValue("5", {
    timeout: 30000,
  });
  await expect(page.getByText("398,850,865", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Execution scope")).not.toContainText(
    "AllocateTensors",
  );
  await page
    .getByTestId("compilation-inspector")
    .locator(":scope > summary")
    .click();
  await expect(page.getByLabel("Execution unit", { exact: true })).toHaveValue(
    "node:4",
  );
  const unit = page.getByTestId("execution-unit-details");
  await expect(unit).toContainText("pinned_reference_integer_rv64imc");
  await expect(unit).toContainText("reference");
  await unit
    .getByText("Prepared parameters · compiler-known values", { exact: true })
    .click();
  await expect(unit.locator("pre").first()).toContainText('"multipliers"');
  await expect(page.getByTestId("planned-memory")).toContainText(
    "1,505,280 bytes",
  );
  await expect(
    page.getByRole("img", {
      name: "Planned memory offsets over execution steps",
    }),
  ).toBeVisible();
  await page
    .getByTestId("compilation-inspector")
    .screenshot({ path: "../build/compiler/checkpoint-3-A0-viewer.png" });
  await page.getByRole("button", { name: /Generated source/ }).click();
  await expect(page.getByLabel("Source file")).toHaveValue(
    "build/compiler/A0/model.cc",
  );
  await page.getByLabel("Execution scope").selectOption("61");
  await expect(page.getByLabel("Execution unit", { exact: true })).toHaveValue(
    "node:60",
  );
  await page
    .getByText("Tensor offsets and alias relationships (1 decision)", {
      exact: true,
    })
    .click();
  await expect(page.getByTestId("planned-memory")).toContainText(
    '"output": 161',
  );
  await page.getByLabel("Execution scope").selectOption("0");
  await expect(page.locator(".scope-count strong")).toHaveText("6,063,975,187");
  await page.getByRole("button", { name: /Advanced Analysis/ }).click();
  await expect(
    page.getByLabel("Compiler unit", { exact: true }),
  ).not.toHaveValue("");
  await expect(
    page.getByLabel("Compiler function", { exact: true }),
  ).not.toHaveValue("");
  await expect(page.locator(".advanced .monaco-editor").first()).toBeVisible();
  expect(errors).toEqual([]);
});

function relationshipBundle(): Buffer {
  const source = strToU8("int fused() { return 0; }\n");
  const hash = (b: Uint8Array) => createHash("sha256").update(b).digest("hex");
  const node = (
    id: string,
    unitIds: string[],
  ): Evidence["graph"]["nodes"][number] => ({
    id,
    index: Number(id),
    type: "TEST",
    group: "TEST",
    inputs: [Number(id)],
    outputs: [Number(id) + 1],
    unitIds,
    disposition: unitIds.length ? "executed" : "eliminated",
    reason: unitIds.length ? undefined : "Read-only view",
    input_shapes: [[1]],
    output_shapes: [[1]],
    logical_macs: "0",
    executed_products: null,
    options: {},
  });
  const unit = (
    id: string,
    order: number,
    nodes: string[],
    eventIds: string[],
  ) => ({
    id,
    order,
    nodes,
    eventIds,
    symbol: "fused",
    implementation: "fixture/fused",
    arithmetic_backend: "scalar",
    inputs: [0],
    outputs: [2],
    source: null,
    memory: null,
    work: {
      logical_macs: null,
      executed_products: null,
      evidence: "unavailable",
    },
    notes: [],
  });
  const event = (
    id: string,
    scope: "inference" | "execution-unit" | "invocation-overhead",
    total: string,
    unitId: string | null,
    nodeId: string | null,
  ): Evidence["events"][number] => ({
    id,
    scope,
    name: id === "root" ? "invoke" : id,
    kind: scope === "execution-unit" ? "operator" : "region",
    total,
    unitId,
    nodeId,
    evidence: scope === "invocation-overhead" ? "derived" : "measured",
    complete: true,
    status: "0",
    entry: "128",
    returnPc: "128",
    counts: total === "0" ? {} : { "128": total },
    mix: {},
  });
  const data: Evidence = {
    schemaVersion: 2,
    provenance: {
      configuration: "relationships",
      compiler: "fixture",
      input_seed: 1,
      output_fnv1a: "fixture",
      hashes: { profile_elf: "fixture" },
      sourceSnapshotStatus: "fixture",
      boundaries: "fixture",
    },
    executionPlan: {
      units: [
        unit("fused", 0, ["0", "1"], ["e0"]),
        unit("split", 1, ["1"], ["e1"]),
      ],
    },
    memoryPlan: null,
    preparedParameters: null,
    graph: {
      nodes: [
        node("0", ["fused"]),
        node("1", ["fused", "split"]),
        node("2", []),
      ],
      tensors: [0, 1, 2, 3].map((id) => ({
        id,
        name: `t${id}`,
        shape: [1],
        type: "INT8",
        constant: false,
        quantization: null,
        producer: id ? String(id - 1) : null,
        consumers: id < 3 ? [String(id)] : [],
      })),
      inputs: [0],
      outputs: [3],
      edges: [1, 2].map((id) => ({
        id: `t${id}`,
        source: String(id - 1),
        target: String(id),
        tensorId: id,
      })),
    },
    events: [
      event("root", "inference", "60", null, null),
      event("e0", "execution-unit", "50", "fused", null),
      event("e1", "execution-unit", "10", "split", "1"),
      event("overhead", "invocation-overhead", "0", null, null),
    ],
    instructions: {
      "128": {
        pc: "128",
        bits: "0x1",
        length: 2,
        mnemonic: "c.nop",
        operands: "",
        category: "integer_alu",
        functionId: "f",
        functionIds: ["f"],
        frames: [
          {
            function: "fused",
            file: "generated.cc",
            line: 1,
            discriminator: 0,
          },
        ],
        transfer: { kind: "next", target: null },
      },
    },
    functions: [
      {
        id: "f",
        name: "fused",
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
    sources: {
      "generated.cc": {
        id: "generated.cc",
        path: "generated.cc",
        archivePath: "sources/generated.txt",
        sha256: hash(source),
        status: "fixture",
      },
    },
    annotations: [],
    compilerUnits: [],
    totals: { inference: "60", allocation: null, overhead: "0" },
    capabilities: {
      compiler: false,
      loops: true,
      sourceMappedInstructions: 1,
      staticInstructions: 1,
    },
  };
  const files = {
    "evidence.json": strToU8(JSON.stringify(data)),
    "sources/generated.txt": source,
  };
  const manifest = {
    format: "riscv-execution-explorer",
    schemaVersion: 2,
    files: Object.fromEntries(
      Object.entries(files).map(([k, v]) => [
        k,
        { sha256: hash(v), size: v.length },
      ]),
    ),
  };
  return Buffer.from(
    zipSync({ ...files, "manifest.json": strToU8(JSON.stringify(manifest)) }),
  );
}

test("split/shared/eliminated graph views preserve costs and missing capabilities", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("Open profile bundle").setInputFiles({
    name: "relationships.zip",
    mimeType: "application/zip",
    buffer: relationshipBundle(),
  });
  const scope = page.getByLabel("Execution scope");
  await expect(scope).toBeVisible();
  await scope.selectOption("logical:0");
  await expect(page.locator(".scope-count strong")).toHaveText("50");
  await expect(
    page.getByText("Shared measurement · full unit cost, not apportioned"),
  ).toBeVisible();
  await scope.selectOption("logical:1");
  await expect(page.locator(".scope-count strong")).toHaveText("60");
  await scope.selectOption("logical:2");
  await expect(page.locator(".scope-count strong")).toHaveText("Unavailable");
  await expect(page.getByText("Read-only view", { exact: true })).toBeVisible();
  await page
    .getByTestId("compilation-inspector")
    .locator(":scope > summary")
    .click();
  await expect(page.getByTestId("compilation-inspector")).toContainText(
    "No compiler memory plan is available",
  );
  await scope.selectOption("e1");
  await expect(page.getByLabel("Execution unit", { exact: true })).toHaveValue(
    "split",
  );
  await scope.selectOption("e0");
  await expect(page.getByLabel("Execution unit", { exact: true })).toHaveValue(
    "fused",
  );
  await page.getByRole("button", { name: /Advanced Analysis/ }).click();
  await expect(page.locator(".advanced-content")).toContainText(
    "Compiler evidence is not included",
  );
  expect(errors).toEqual([]);
});
