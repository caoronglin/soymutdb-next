import { defineConfig } from "@playwright/test";

/**
 * Local E2E for the Phase 4/8 public UI (homepage/search/genes/accessibility/
 * BLAST/login). Offline-capable where possible; the static server supplies
 * only the deterministic API mocks required by an interaction test.
 *
 * Requires a built dist (apps/web/dist) — the webServer starts
 * e2e/static-server.mjs which serves the dist at /soymutdb-next with SPA
 * fallback. The SPA bootstraps from the immutable seed definition when the API
 * is unavailable (apps/web/src/page-builder/loader.ts).
 *
 * Run from e2e/:  npx playwright test -c playwright-public.config.ts
 */
const baseURL = "http://localhost:4173/soymutdb-next/";

export default defineConfig({
  testDir: "./tests",
  testMatch: /(homepage|search|genes|accessibility|blast|public-login)\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-public" }],
  ],
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-public",
  webServer: {
    command: "node static-server.mjs",
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
