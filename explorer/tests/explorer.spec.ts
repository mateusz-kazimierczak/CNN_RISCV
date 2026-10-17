import { test, expect } from "@playwright/test";
import { existsSync } from "node:fs";
test.skip(
  !existsSync("../build/explorer/B0.zip"),
  "Export local B0 before running browser acceptance",
);
test("real B0 operator → loop → source → GCC workflow", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Explore B0 baseline" }).click();
  await expect(page.getByLabel("Execution scope")).toHaveValue("6", {
    timeout: 30000,
  });
  await expect(page.getByText("327,839,821", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Source file")).toContainText("conv.h");
  await expect(
    page.getByRole("button", { name: /Advanced Analysis/ }),
  ).toHaveAttribute("aria-expanded", "false");
  const assemblyAnalysis = page.getByRole("button", {
    name: "Assembly Analysis",
    exact: false,
  });
  await expect(assemblyAnalysis).toHaveAttribute("aria-expanded", "false");
  await assemblyAnalysis.click();
  await page
    .getByRole("button")
    .filter({ hasText: /loop · 8 instr/ })
    .click();
  await expect(page.getByText("SELECTED NATURAL LOOP")).toBeVisible();
  await expect(
    page.getByText("Product and accumulation", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "0x80005ca2", exact: true }).click();
  await expect(page.getByTestId("instruction-detail")).toContainText("mulw");
  await expect(page.getByLabel("Source file")).toHaveValue(
    ".deps/tflite-micro/tensorflow/lite/kernels/internal/reference/integer_ops/conv.h",
  );
  await page
    .locator(".source-code .view-line")
    .filter({ hasText: /acc.*filter_val.*input_val/ })
    .click({ position: { x: 10, y: 10 } });
  await expect(page.getByTestId("source-match-count")).toHaveText(
    "3 SOURCE MATCHES",
  );
  await expect(
    page.locator(".assembly-code .view-overlays .source-linked"),
  ).toHaveCount(3);
  await expect(page.locator(".run-summary")).toHaveCount(0);
  await assemblyAnalysis.click();
  await expect(page.getByLabel("RISC-V assembly")).toBeVisible();
  await assemblyAnalysis.click();
  await page.getByLabel("Execution scope").selectOption("1");
  await expect(page.getByText("4,867,278,370", { exact: true })).toBeVisible();
  await page
    .getByRole("button")
    .filter({ hasText: /loop · 8 instr/ })
    .click();
  await expect(page.locator(".loop-stats")).toContainText("2.794B");
  await page.getByRole("button", { name: /Advanced Analysis/ }).click();
  if (await page.getByLabel("Compiler unit").count()) {
    await expect(page.getByLabel("Compiler unit")).not.toHaveValue("");
    await expect(
      page.getByLabel("Compiler function", { exact: true }),
    ).not.toHaveValue("");
    await page.getByLabel("Compare preceding stage").check();
    await expect(page.locator(".monaco-diff-editor")).toBeVisible();
  }
  await page
    .getByRole("button", { name: "Previous selection", exact: true })
    .click();
  expect(errors).toEqual([]);
});
test("upload rejection leaves the current bundle reviewable", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore B0 baseline" }).click();
  await expect(page.getByLabel("Execution scope")).toBeVisible({
    timeout: 30000,
  });
  await page.getByLabel("Open profile bundle").setInputFiles({
    name: "invalid.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("bad data"),
  });
  await expect(page.getByRole("alert", { name: "Bundle import error" })).toBeVisible();
  await expect(page.getByLabel("Execution scope")).toHaveValue("6");
});

test("register clicks distinguish recorded variables and inferred expressions", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore B0 baseline" }).click();
  await expect(page.getByLabel("Execution scope")).toBeVisible({
    timeout: 30000,
  });
  const acc = page
    .locator(".assembly-code .view-line")
    .filter({ hasText: /0x80005ca8/ })
    .getByText("x10", { exact: true })
    .first();
  await acc.click();
  const popover = page.getByRole("dialog", { name: "Register x10" });
  await expect(popover.getByText("acc", { exact: true })).toBeVisible();
  await expect(popover).toContainText("variable value");
  await popover.getByRole("button", { name: "conv.h:79" }).click();
  await expect(popover).not.toBeVisible();
  await expect(page.locator(".line-indicator")).toHaveText("L79");
  await page
    .locator(".assembly-code .view-line")
    .filter({ hasText: /0x80005c9e/ })
    .getByText("x8", { exact: true })
    .click();
  await expect(page.getByRole("dialog", { name: "Register x8" })).toContainText(
    "input_offset",
  );
  await expect(page.getByRole("dialog", { name: "Register x8" })).toContainText(
    "Inferred expression",
  );
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page
    .locator(".assembly-code .view-line")
    .filter({ hasText: /0x80005ca2/ })
    .getByText("x23", { exact: true })
    .click();
  const expression = page.getByRole("dialog", { name: "Register x23" });
  await expect(expression).toContainText("input_val + input_offset");
  await expect(expression).toContainText("Inferred expression");
  await expression.getByText("Instruction evidence", { exact: true }).click();
  await expect(expression).toContainText("addw x23,x23,x8");
});

test("instruction clicks explain compressed stack stores without line hovers", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore B0 baseline" }).click();
  await expect(page.getByLabel("Execution scope")).toBeVisible({
    timeout: 30000,
  });
  const editor = page.getByRole("textbox", {
    name: "RISC-V assembly",
    exact: true,
  });
  await editor.press("Control+g");
  await page
    .getByRole("textbox", {
      name: "Go to line. Type a line number, optionally followed by colon and column number.",
      exact: true,
    })
    .fill(":22");
  await page
    .getByRole("textbox", {
      name: "Go to line. Type a line number, optionally followed by colon and column number.",
      exact: true,
    })
    .press("Enter");
  const mnemonic = page
    .locator(".assembly-code .view-line")
    .filter({ hasText: /0x80005b22/ })
    .getByText("c.sdsp", { exact: true });
  await mnemonic.hover();
  // Monaco used to open the unwanted decoration hover after its hover delay.
  await page.waitForTimeout(800);
  await expect(page.locator(".monaco-hover:visible")).toHaveCount(0);
  await mnemonic.click();
  const help = page.getByRole("dialog", {
    name: "Instruction c.sdsp",
    exact: true,
  });
  await expect(help).toContainText("Write 8 bytes from x23");
  await expect(help).toContainText("sd x23,216(x2)");
  await expect(help).toContainText("16-bit encoding");
  await page.keyboard.press("Escape");
  await expect(help).not.toBeVisible();
  await page.keyboard.press("Enter");
  await expect(help).toBeVisible();
  await page
    .getByRole("button", { name: "Close instruction inspector" })
    .click();
  await page
    .locator(".assembly-code .view-line")
    .filter({ hasText: /0x80005b22/ })
    .getByText("x23", { exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Register x23", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("dialog", { name: "Instruction c.sdsp", exact: true }),
  ).not.toBeVisible();
});

test("source variables show layer values and loop bounds", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore B0 baseline" }).click();
  await expect(page.getByLabel("Execution scope")).toBeVisible({
    timeout: 30000,
  });
  const goTo = async (line: number) => {
    await page
      .getByRole("textbox", { name: "C++ source", exact: true })
      .press("Control+g");
    const input = page.getByRole("textbox", {
      name: "Go to line. Type a line number, optionally followed by colon and column number.",
      exact: true,
    });
    await input.fill(`:${line}`);
    await page.keyboard.press("Enter");
  };
  await goTo(52);
  await page
    .locator(".source-code .view-line")
    .getByText("batches", { exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Source variable batches", exact: true }),
  ).toContainText("batches = 1");
  await expect(page.getByRole("dialog")).toContainText("Model-derived value");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("dialog", { name: "Source variable batches", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await goTo(72);
  await page
    .locator(".source-code .view-line")
    .getByText("batch", { exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("dialog", { name: "Source variable batch", exact: true }),
  ).toContainText("Loop variable");
  await expect(page.getByRole("dialog")).toContainText("0 ≤ batch < 1");
  await expect(page.getByRole("dialog")).not.toContainText("batch = 1");
});

test("assembly target labels are readable and raw symbols remain inspectable", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore B0 baseline" }).click();
  await expect(page.getByLabel("Execution scope")).toBeVisible({
    timeout: 30000,
  });
  const branch = page
    .locator(".assembly-code .view-line")
    .filter({ hasText: /0x80005cac/ });
  await expect(branch).toContainText("x27,x14,0x80005c94");
  await expect(branch).toContainText("ConvPerChannel + 0x1aa");
  await expect(branch).not.toContainText("_ZN6tflite");
  await branch.getByText("bne", { exact: true }).click();
  const help = page.getByRole("dialog", {
    name: "Instruction bne",
    exact: true,
  });
  await expect(help).toContainText("Jump to 0x80005c94");
  await help.getByText("Original disassembly", { exact: true }).click();
  await expect(help.locator("details")).toContainText(
    "_ZN6tflite21reference_integer_ops14ConvPerChannel",
  );
});

test("target addresses jump to instructions and preserve selection history", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore B0 baseline" }).click();
  await expect(page.getByLabel("Execution scope")).toBeVisible({
    timeout: 30000,
  });
  const branch = page
    .locator(".assembly-code .view-line")
    .filter({ hasText: /0x80005cac/ });
  await branch.getByText("bne", { exact: true }).click();
  await page.keyboard.press("Escape");
  await branch.getByText("0x80005c94", { exact: true }).click();
  await expect(page.getByTestId("instruction-detail")).toContainText(
    "0x80005c94",
  );
  await expect(page.getByTestId("instruction-detail")).toContainText("lb");
  await expect(page.getByLabel("Execution scope")).toHaveValue("6");
  await page
    .getByRole("button", { name: "Previous selection", exact: true })
    .click();
  await expect(page.getByTestId("instruction-detail")).toContainText(
    "0x80005cac",
  );
  await branch.getByText("bne", { exact: true }).click();
  await page
    .getByRole("dialog", { name: "Instruction bne", exact: true })
    .getByRole("button", { name: "Go to 0x80005c94", exact: true })
    .click();
  await expect(page.getByTestId("instruction-detail")).toContainText(
    "0x80005c94",
  );
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page
    .getByRole("textbox", { name: "RISC-V assembly", exact: true })
    .press("Control+g");
  await page
    .getByRole("textbox", {
      name: "Go to line. Type a line number, optionally followed by colon and column number.",
      exact: true,
    })
    .fill(":186");
  await page.keyboard.press("Enter");
  await page
    .locator(".assembly-code .view-line")
    .filter({ hasText: /0x80005cec/ })
    .getByText("0x8000dcdc", { exact: true })
    .click();
  await expect(page.getByTestId("instruction-detail")).toContainText(
    "0x8000dcdc",
  );
  await expect(page.getByLabel("Function", { exact: true })).toHaveAttribute(
    "title",
    "tflite::MultiplyByQuantizedMultiplier(int, int, int)",
  );
  await page
    .getByRole("button", { name: "Previous selection", exact: true })
    .click();
  await expect(page.getByTestId("instruction-detail")).toContainText(
    "0x80005cec",
  );
});

test("pointer registers expose scoped source, instruction, and compiler evidence", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore B0 baseline" }).click();
  await expect(page.getByLabel("Execution scope")).toHaveValue("6", {
    timeout: 30000,
  });
  const branch = page
    .locator(".assembly-code .view-line")
    .filter({ hasText: /0x80005cac/ });
  await branch.getByText("x14", { exact: true }).click();
  const pointer = page.getByRole("dialog", {
    name: "Register x14",
    exact: true,
  });
  await expect(pointer).toContainText("Pointer used for filter_val");
  await expect(pointer).toContainText(
    "Nearby DWARF relationship; valid before 0x80005cac",
  );
  await expect(pointer).toContainText("signed_byte_at(x14 - 1)");
  await expect(pointer).toContainText("16 bytes for the selected operator");
  await pointer.getByText("Supporting evidence", { exact: true }).click();
  await pointer
    .getByRole("button", { name: /filter_input_depth · conv.h:64/ })
    .click();
  await expect(
    page
      .locator(".source-code .view-line")
      .filter({ hasText: /const\s+int\s+filter_input_depth/ }),
  ).toBeVisible();
  await branch.getByText("x27", { exact: true }).click();
  const boundary = page.getByRole("dialog", {
    name: "Register x27",
    exact: true,
  });
  await expect(boundary).toContainText("Loop end pointer");
  await expect(boundary).toContainText("initial(x14) + filter_input_depth");
  await boundary.getByText("Supporting evidence", { exact: true }).click();
  await boundary.getByRole("button", { name: /0x80005c98 · lb/ }).click();
  await expect(page.getByTestId("instruction-detail")).toContainText(
    "0x80005c98",
  );
  await branch.getByText("x27", { exact: true }).click();
  await boundary.getByText("Supporting evidence", { exact: true }).click();
  await boundary
    .getByRole("button", { name: "Open final RTL · _90", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /Advanced Analysis/ }),
  ).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByLabel("Compiler stage")).toHaveValue("Final RTL");
  await expect(
    page
      .locator(".compiler-editor .view-line")
      .filter({ hasText: /reg:DI\s+27\s+s11\s+\[orig:192\s+_90/ }),
  ).toBeVisible();
});

test("graph measurements survive unrelated renders, selection changes and pane resizing", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore B0 baseline" }).click();
  const graph = page.locator(".graph-wrap");
  const visibleNodes = async () =>
    graph.locator(".react-flow__node").evaluateAll((els) => ({
      total: els.length,
      hidden: els.filter((el) => getComputedStyle(el).visibility === "hidden")
        .length,
    }));
  await expect
    .poll(visibleNodes, { timeout: 30000 })
    .toEqual({ total: 64, hidden: 0 });
  for (const scope of ["5", "6", "4", "1", "6"]) {
    await page.getByLabel("Execution scope").selectOption(scope);
    await expect.poll(visibleNodes).toEqual({ total: 64, hidden: 0 });
    await page.getByRole("button", { name: /Assembly Analysis/ }).click();
    await expect.poll(visibleNodes).toEqual({ total: 64, hidden: 0 });
  }
  // A vertical SVG path has a zero-width geometry box even with a visible
  // stroke; Playwright's box-based visibility check calls that hidden.
  const edge = graph.locator(".react-flow__edge-path").first();
  await expect(edge).toHaveAttribute("d", /^M.+C/);
  await expect(edge).toHaveCSS("visibility", "visible");
  await expect(edge).toHaveCSS("stroke-width", "1.4px");
});
