import { defineConfig } from "@playwright/test";

/**
 * Deployed-stack E2E for the React JBrowse shell and the portal /browser embed.
 *
 * This suite needs BOTH a deployed React shell (JBROWSE_BASE_URL) and a deployed
 * portal whose /browser route embeds it (PORTAL_BASE_URL). It is deliberately
 * not part of the offline static-server suites: e2e/static-server.mjs serves
 * only apps/web/dist and knows nothing about the shell or /jbrowse-data.
 *
 * Run:
 *   JBROWSE_BASE_URL=https://jbrowse.soymutdb.test/ \
 *   PORTAL_BASE_URL=https://soymutdb.test/ \
 *     npx playwright test -c playwright-jbrowse.config.ts
 *
 * Set only the variable whose stack is available; the missing side's tests
 * report as skipped instead of failing.
 */
const baseURL =
  process.env.PORTAL_BASE_URL ??
  process.env.SMOKE_BASE_URL ??
  "http://localhost:4173";

export default defineConfig({
  testDir: "./tests",
  testMatch: /jbrowse-browser\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-jbrowse" }],
  ],
  use: {
    baseURL,
    // The shell chrome is English; pin the browser locale so host detection
    // cannot switch the portal's i18n and surprise the assertions.
    locale: "en-US",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-jbrowse",
});
