import { test, expect } from "@playwright/test";

test.skip(
  !process.env.SIMULATOR_V2_BROWSER_URL,
  "Start gmake compiler-app-dev and set SIMULATOR_V2_BROWSER_URL",
);
test("B1 v2 live stages, registers, source, breakpoints, memory and replay", async ({
  page,
}) => {
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(process.env.SIMULATOR_V2_BROWSER_URL!);
  await page.getByRole("tab", { name: /^Simulator/ }).click();
  await expect(
    page.getByRole("button", { name: "Start", exact: true }),
  ).toBeEnabled({ timeout: 30000 });
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page.locator(".sim-position")).toContainText("inference entry", {
    timeout: 30000,
  });
  const destination = page.getByLabel("Destination stage");
  await expect(destination.locator("option")).toHaveCount(64);
  await destination.selectOption("1");
  await page.getByRole("button", { name: "Run to stage", exact: true }).click();
  await expect(page.locator(".sim-model .sim-pane-heading")).toContainText(
    "NODE 1 ACTIVE",
    { timeout: 30000 },
  );
  await expect(page.locator(".sim-position")).toContainText("stage breakpoint");
  const before = await page.locator(".sim-position strong").last().innerText();
  await page.getByRole("button", { name: "Step", exact: true }).click();
  await expect
    .poll(async () =>
      (
        await page.locator(".sim-position strong").last().innerText()
      ).replaceAll(",", ""),
    )
    .toBe((BigInt(before.replaceAll(",", "")) + 1n).toString());
  await expect(page.getByLabel("Simulator source file")).not.toHaveValue("");
  await page
    .locator(".sim-register-grid button")
    .filter({ hasText: /^x2sp/ })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Live register value");
  await page.keyboard.press("Escape");
  await page
    .locator(".sim-workspace")
    .screenshot({ path: "../build/simulator/B1-spatial2-oc2/browser-v2.png" });
  await page
    .locator(".sim-utilities summary")
    .filter({ hasText: "Breakpoints" })
    .click();
  await destination.selectOption("2");
  await page
    .getByRole("button", { name: "Break on stage entry", exact: true })
    .click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.locator(".sim-position")).toContainText("breakpoint", {
    timeout: 30000,
  });
  await expect(page.locator(".sim-model .sim-pane-heading")).toContainText(
    "NODE 2 ACTIVE",
  );
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await page
    .locator(".sim-utilities summary")
    .filter({ hasText: "Memory" })
    .click();
  await page.getByLabel("Memory address").fill("0x80000000");
  await page.getByLabel("Memory byte count").fill("16");
  await page.getByRole("button", { name: "Read RAM", exact: true }).click();
  await expect(page.locator(".sim-utilities pre").first()).toContainText(
    "0x80000000",
  );
  await destination.selectOption("0");
  await page.getByRole("button", { name: "Run to stage", exact: true }).click();
  await expect(page.locator(".sim-model .sim-pane-heading")).toContainText(
    "NODE 0 ACTIVE",
    { timeout: 30000 },
  );
  await page.getByRole("tab", { name: "Explorer", exact: true }).click();
  await page
    .getByRole("button", { name: /Explore B1-spatial2-oc2 build/ })
    .click();
  await expect(page.getByLabel("Execution scope")).toBeVisible({
    timeout: 30000,
  });
  await page.getByRole("tab", { name: /^Simulator/ }).click();
  await expect(page.locator(".sim-model .sim-pane-heading")).toContainText(
    "NODE 0 ACTIVE",
  );
  expect(errors).toEqual([]);
});
