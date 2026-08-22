import { defineConfig } from "@playwright/test";

/**
 * Production-artifact gate for the Admin login page.
 *
 * The server below serves apps/admin/dist directly. It is intentionally not a
 * Vite development server, so an emitted-bundle failure cannot be masked by
 * source transforms or HMR.
 */
const baseURL = "http://127.0.0.1:4174";

export default defineConfig({
  testDir: "./tests",
  testMatch: /admin-production-login\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-admin-production" }],
  ],
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-admin-production",
  webServer: {
    command: "node admin-static-server.mjs",
    cwd: ".",
    url: baseURL,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
