import { defineConfig } from "@playwright/test";

/**
 * Local E2E for the primer-design page (pure-frontend, offline).
 *
 * Requires a built dist (apps/web/dist) — the webServer starts
 * e2e/static-server.mjs which serves the dist at /soymutdb-next with an
 * SPA fallback and a mocked /api/v1/tools/seqfetch endpoint, so the
 * "from genome" mode works without a backend.
 *
 * Run from e2e/:  npx playwright test -c playwright-primer.config.ts
 * CI: .github/workflows/primer-e2e.yml builds the web app first.
 */
const baseURL = "http://localhost:4173/soymutdb-next/";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/primer-design.spec.ts",
  workers: 1,
  fullyParallel: false,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-primer" }],
  ],
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-primer",
  webServer: {
    command: "node static-server.mjs",
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
