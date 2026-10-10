import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  timeout: 120_000,
  expect: { timeout: 12_000 },
  reporter: "list",
  use: {
    baseURL: process.env.PURCHASEFLOW_WEB_URL ?? "http://127.0.0.1:18081",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
