import { defineConfig } from "@playwright/test";

/**
 * Local browser performance evidence for the already-built public Web artifact.
 *
 * This measures the emitted production files through the repository static
 * server; it deliberately does not use Vite dev mode and does not claim field
 * Core Web Vitals percentiles. The test writes a reproducible JSON report to
 * test-results-web-performance/performance-report.json.
 */
// The checked-in validation artifact is built with Vite's root base path. The
// separate deployed-site smoke suite covers the gh-pages sub-path deployment.
const baseURL = "http://127.0.0.1:4175/";

export default defineConfig({
  testDir: "./tests",
  testMatch: /web-artifact-performance\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 45_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["json", { outputFile: "test-results-web-performance/playwright-report.json" }],
  ],
  use: {
    baseURL,
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  outputDir: "test-results-web-performance/artifacts",
  webServer: {
    command: "node static-server.mjs ../apps/web/dist 4175 /",
    cwd: ".",
    url: baseURL,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
