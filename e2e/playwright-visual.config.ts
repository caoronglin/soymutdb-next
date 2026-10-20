import { defineConfig } from "@playwright/test";

/**
 * Screenshot and geometry audit for the local public artifact.
 * Build apps/web/dist first, then run from e2e/:
 *   npm run test:visual
 */
// `build:sites` emits `dist/external` with the root base ("/"); serve that tree
// at the origin root so the layout audit measures the real artifact.
const baseURL = process.env.VISUAL_BASE_URL ?? "http://localhost:4177/";

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
        command: "node static-server.mjs ../apps/web/dist/external 4177 /",
        url: baseURL,
        reuseExistingServer: false,
        timeout: 30_000,
      },
});
