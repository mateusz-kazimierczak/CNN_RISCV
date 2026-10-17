import { test, expect } from "@playwright/test";
// The backend owns a real guest process. Opt in to this suite with a standalone
// server; ordinary offline-explorer browser checks do not launch simulations.
test.skip(
  !process.env.SIMULATOR_BROWSER_URL,
  "Set SIMULATOR_BROWSER_URL to a running standalone debugger",
);
test("real simulation: stage breakpoint, loop stepping, static browsing, live values, memory and replay", async ({
  page,
}) => {
  test.setTimeout(180000);
  await page.goto(process.env.SIMULATOR_BROWSER_URL!);
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
  const functions = page.getByLabel("Simulator function");
  const conv = await functions
    .locator("option")
    .filter({ hasText: /reference_integer_ops::ConvPerChannel/ })
    .first()
    .getAttribute("value");
  await functions.selectOption(conv!);
  await page
    .getByRole("textbox", { name: "Simulator RISC-V assembly", exact: true })
    .press("Control+g");
  await page
    .getByRole("textbox", {
      name: "Go to line. Type a line number, optionally followed by colon and column number.",
      exact: true,
    })
    .fill(":161");
  await page.keyboard.press("Enter");
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
