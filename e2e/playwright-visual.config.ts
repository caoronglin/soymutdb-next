import { defineConfig } from "@playwright/test";

/**
 * Screenshot and geometry audit for the local public artifact.
 * Build apps/web/dist first, then run from e2e/:
 *   npm run test:visual
 */
const baseURL = process.env.VISUAL_BASE_URL ?? "http://localhost:4175/soymutdb-next/";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/visual-layout.spec.ts",
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 12_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report-visual" }]],
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-visual",
  webServer: process.env.VISUAL_BASE_URL
    ? undefined
    : {
        command: "node static-server.mjs ../apps/web/dist 4175 /soymutdb-next",
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 30_000,
      },
});
