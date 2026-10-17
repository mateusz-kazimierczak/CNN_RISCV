import { test, expect } from "@playwright/test";
// The backend owns a real guest process. Opt in to this suite with the unified
// server; ordinary offline-explorer browser checks do not launch simulations.
test.skip(
  !process.env.SIMULATOR_BROWSER_URL,
  "Set SIMULATOR_BROWSER_URL to the running app (use /#simulator)",
);
test("real simulation: stage breakpoint, loop stepping, static browsing, live values, memory and replay", async ({
  page,
}) => {
  test.setTimeout(180000);
  await page.goto(process.env.SIMULATOR_BROWSER_URL!);
  await page.getByRole("tab", { name: /^Simulator/ }).click();
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page.locator(".sim-position")).toContainText("inference entry", {
    timeout: 30000,
  });
  await page.getByLabel("Destination stage").selectOption("1");
  await page.getByRole("button", { name: "Run to stage", exact: true }).click();
  await expect(page.locator(".sim-position")).toContainText(
    "stage breakpoint",
    { timeout: 30000 },
  );
  await expect(page.locator(".sim-model .sim-pane-heading")).toContainText(
    "NODE 1 ACTIVE",
  );
  await expect(page.locator(".sim-listing-scope")).toContainText(
    "35,754 instructions",
  );
  await page.getByLabel("Jump to instruction address").fill("0x8001c8c0");
  await page.getByRole("button", { name: "Go", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("No decoded instruction");
  const functions = page.getByLabel("Jump to function");
  const conv = await functions
    .locator("option")
    .filter({ hasText: /reference_integer_ops::ConvPerChannel/ })
    .first()
    .getAttribute("value");
  await functions.selectOption(conv!);
  await page.getByLabel("Jump to instruction address").fill("0x80005cac");
  await page.getByRole("button", { name: "Go", exact: true }).click();
  await page
    .locator(".sim-assembly .view-line")
    .filter({ hasText: /0x80005cac/ })
    .getByText("bne", { exact: true })
    .click();
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Break at selection", exact: true })
    .click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.locator(".sim-position")).toContainText("0x80005cac", {
    timeout: 30000,
  });
  await page
    .locator(".sim-assembly .view-line")
    .filter({ hasText: /0x80005cac/ })
    .getByText("x27", { exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Register x27", exact: true }),
  ).toContainText("Live register value");
  await expect(page.getByRole("dialog")).toContainText("Loop end pointer");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Step", exact: true }).click();
  await expect(page.locator(".sim-position")).toContainText("0x80005c94");
  const memcpy = await functions
    .locator("option")
    .filter({ hasText: /^memcpy$/ })
    .getAttribute("value");
  await functions.selectOption(memcpy!);
  await expect(page.locator(".sim-position")).toContainText("0x80005c94");
  await page.getByRole("button", { name: "Follow PC", exact: true }).click();
  await expect(
    page.locator(".sim-assembly .view-line").filter({ hasText: /0x80005c94/ }),
  ).toBeVisible();
  await page
    .locator(".sim-utilities summary")
    .filter({ hasText: /Memory/ })
    .click();
  await page.getByLabel("Memory address").fill("0x80000000");
  await page.getByLabel("Memory byte count").fill("16");
  await page.getByRole("button", { name: "Read RAM", exact: true }).click();
  await expect(page.locator(".sim-utilities pre").first()).toContainText(
    "0x80000000",
  );
  await page.getByLabel("Destination stage").selectOption("0");
  await page.getByRole("button", { name: "Run to stage", exact: true }).click();
  await expect(page.locator(".sim-model .sim-pane-heading")).toContainText(
    "NODE 0 ACTIVE",
    { timeout: 30000 },
  );
  await expect(page.locator(".sim-position")).toContainText("stage breakpoint");
  await expect(page.locator(".sim-utilities summary").first()).toContainText(
    "1",
  );
});

test("workspace tabs retain profile selection and paused simulation without hidden shortcuts", async ({
  page,
}) => {
  await page.goto(new URL("/", process.env.SIMULATOR_BROWSER_URL!).href);
  await page.getByRole("button", { name: "Explore B0 baseline" }).click();
  await expect(page.getByLabel("Execution scope")).toHaveValue("6", {
    timeout: 30000,
  });
  await page.getByLabel("Execution scope").selectOption("1");
  await page.getByRole("tab", { name: "Simulator", exact: true }).click();
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page.locator(".sim-position")).toContainText("inference entry", {
    timeout: 30000,
  });
  const position = await page.locator(".sim-position").innerText();
  await page.getByRole("tab", { name: "Explorer", exact: true }).click();
  await expect(page.getByLabel("Execution scope")).toHaveValue("1");
  await page.keyboard.press("F10");
  await page.keyboard.press("F8");
  await page.getByRole("tab", { name: /Simulator PAUSED/i }).click();
  await expect(page.locator(".sim-position")).toHaveText(position);
  await page.getByRole("button", { name: "Step", exact: true }).click();
  await expect(page.locator(".sim-position")).not.toHaveText(position);
  await page.getByRole("tab", { name: "Explorer", exact: true }).click();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: /Simulator/i })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("ArrowLeft");
  await expect(
    page.getByRole("tab", { name: "Explorer", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.goBack();
  await expect(page.getByRole("tab", { name: /Simulator/i })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test("assembly-first debugger gutter, prepared breakpoints, F9 and independent PC marker", async ({
  page,
}) => {
  await page.goto(
    new URL("/#simulator", process.env.SIMULATOR_BROWSER_URL!).href,
  );
  const panes = page.locator(".sim-workspace > section");
  await expect(panes).toHaveCount(3);
  expect(
    await panes.evaluateAll((els) =>
      els.map((el) => el.getAttribute("aria-label")),
    ),
  ).toEqual(["Assembly debugger", "C++ source context", "Model context"]);
  await expect(
    page.getByRole("button", { name: "Start", exact: true }),
  ).toBeEnabled();
  const jump = page.getByLabel("Jump to instruction address");
  await jump.fill("0x80005cac");
  await page.getByRole("button", { name: "Go", exact: true }).click();
  const row = page
    .locator(".sim-assembly .view-line")
    .filter({ hasText: /^0x80005cac/ });
  await expect(row).toBeVisible();
  const before = await row.boundingBox();
  const margin = await page.locator(".sim-assembly .margin").boundingBox();
  await page.mouse.click(margin!.x + 11, before!.y + before!.height / 2);
  await expect(
    page.getByRole("button", { name: "Remove breakpoint", exact: true }),
  ).toBeEnabled();
  await expect(page.locator(".sim-assembly .sim-breakpoint-glyph")).toHaveCount(
    1,
  );
  expect((await row.boundingBox())!.x).toBe(before!.x);
  await page.keyboard.press("F9");
  await expect(
    page.getByRole("button", { name: "Break at selection", exact: true }),
  ).toBeEnabled();
  await page.keyboard.press("F9");
  await expect(
    page.getByRole("button", { name: "Remove breakpoint", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page.locator(".sim-position")).toContainText("inference entry", {
    timeout: 30000,
  });
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.locator(".sim-position")).toContainText("0x80005cac", {
    timeout: 30000,
  });
  await expect(page.locator(".sim-assembly .sim-pc-glyph")).toHaveCount(1);
  await expect(page.locator(".sim-assembly .sim-breakpoint-glyph")).toHaveCount(
    1,
  );
  await expect(page.getByRole("status")).toContainText(
    "Paused before instruction 0x80005cac",
  );
  const stopped = await page.locator(".sim-position").innerText();
  const now = await row.boundingBox();
  const currentMargin = await page
    .locator(".sim-assembly .margin")
    .boundingBox();
  await page.mouse.click(currentMargin!.x + 11, now!.y + now!.height / 2);
  await expect(
    page.getByRole("button", { name: "Break at selection", exact: true }),
  ).toBeEnabled();
  await expect(page.locator(".sim-assembly .sim-pc-glyph")).toHaveCount(1);
  expect(await page.locator(".sim-position").innerText()).toBe(stopped);
  await page.getByRole("button", { name: "Step", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(
    "Paused before instruction 0x80005c94",
  );
  await page
    .getByRole("separator", { name: "Resize assembly and C++ panes" })
    .press("ArrowRight");
  await expect(
    page.getByRole("separator", { name: "Resize assembly and C++ panes" }),
  ).toHaveAttribute("aria-valuenow", "52");
});

test("model remains visible while stepping helpers, resizing and switching tabs", async ({
  page,
}) => {
  test.setTimeout(120000);
  await page.goto(
    new URL("/#simulator", process.env.SIMULATOR_BROWSER_URL!).href,
  );
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page.locator(".sim-position")).toContainText("inference entry", {
    timeout: 30000,
  });
  await page.getByLabel("Destination stage").selectOption("3");
  await page.getByRole("button", { name: "Run to stage", exact: true }).click();
  await expect(page.locator(".sim-model .sim-pane-heading")).toContainText(
    "NODE 3 ACTIVE",
    { timeout: 30000 },
  );
  const visibleNodes = async () =>
    page.locator(".sim-graph .react-flow__node").evaluateAll((els) => ({
      total: els.length,
      hidden: els.filter((el) => getComputedStyle(el).visibility === "hidden")
        .length,
    }));
  for (let i = 0; i < 12; i++) {
    await page.getByRole("button", { name: "Step", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Step", exact: true }),
    ).toBeEnabled();
    await expect.poll(visibleNodes).toEqual({ total: 64, hidden: 0 });
  }
  for (let i = 0; i < 3; i++) {
    await page.getByRole("tab", { name: "Explorer", exact: true }).click();
    await page.getByRole("tab", { name: /Simulator/i }).click();
    await page
      .getByRole("separator", { name: "Resize C++ and model panes" })
      .press(i % 2 ? "ArrowLeft" : "ArrowRight");
    await expect.poll(visibleNodes).toEqual({ total: 64, hidden: 0 });
  }
  const selected = page.locator('.sim-graph .react-flow__node[data-id="3"]');
  await expect
    .poll(async () =>
      selected.evaluate((el) => {
        const r = el.getBoundingClientRect(),
          p = el.closest(".sim-graph")!.getBoundingClientRect();
        return (
          r.right > p.left &&
          r.left < p.right &&
          r.bottom > p.top &&
          r.top < p.bottom
        );
      }),
    )
    .toBe(true);
});
