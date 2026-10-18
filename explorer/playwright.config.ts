import { defineConfig } from "@playwright/test";
const port = Number(process.env.EXPLORER_TEST_PORT || 5173);
if (!Number.isInteger(port) || port < 1024 || port > 65535)
  throw new Error("Invalid EXPLORER_TEST_PORT");
const baseURL = `http://127.0.0.1:${port}`;
export default defineConfig({
  testDir: "./tests",
  timeout: 60000,
  use: {
    baseURL,
    viewport: { width: 1600, height: 1100 },
    headless: true,
  },
  webServer: {
    command: `npm run dev -- --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
  reporter: "list",
});
