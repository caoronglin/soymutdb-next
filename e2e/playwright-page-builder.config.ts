import { defineConfig } from "@playwright/test";

/**
 * Offline browser E2E for the built Admin page-builder editor.
 * The browser spec fulfills its authenticated API reads with deterministic
 * fixtures; the server only serves the emitted production artifact.
 */
export default defineConfig({
  testDir: "./tests",
  testMatch: /page-builder-drag\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report-page-builder" }]],
  use: {
    baseURL: "http://127.0.0.1:4176",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-page-builder",
  webServer: {
    command: "node admin-static-server.mjs ../apps/admin/dist 4176",
    cwd: ".",
    url: "http://127.0.0.1:4176",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
