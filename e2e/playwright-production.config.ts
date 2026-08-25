import { defineConfig } from "@playwright/test";

/**
 * PRODUCTION E2E hard gate.
 *
 * This is the strict, release-data gate (distinct from the gh-pages DEMO
 * smoke in playwright.config.ts / online-smoke.spec.ts). It runs against a
 * REAL production / staging deployment and asserts that release data is
 * actually served:
 *   - no API 404/405 on the data endpoints (the SPA must NOT be in a fallback
 *     state),
 *   - no demo/placeholder content (SMDB-00001, "Demo fixture", localhost,
 *     example.com, change-me) embedded in any key page,
 *   - the public portal, JBrowse and Admin console are reachable and render.
 *
 * Target the deployment with PRODUCTION_BASE_URL (required). This config is
 * intentionally separate from the demo smoke so the two can be run and gated
 * independently; the demo artifact is allowed to contain fixture data, the
 * production gate is not.
 *
 * Run:
 *   PRODUCTION_BASE_URL=https://soymutdb.org \
 *     npx playwright test -c playwright-production.config.ts
 *
 * Local (against a locally-served production dist):
 *   PRODUCTION_BASE_URL=http://localhost:4180/prod/ \
 *     npx playwright test -c playwright-production.config.ts
 */
const baseURL = process.env.PRODUCTION_BASE_URL;

export default defineConfig({
  testDir: "./tests",
  testMatch: /production-gate\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-production" }],
  ],
  use: {
    baseURL: baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-production",
});
