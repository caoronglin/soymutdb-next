import { defineConfig } from "@playwright/test";

/**
 * Deployed-stack regression for the portal /browser JBrowse embed.
 *
 * It needs only a deployed public portal that embeds the shell (PORTAL_BASE_URL,
 * or SMOKE_BASE_URL as a fallback); the standalone shell suite keeps its own
 * config in playwright-jbrowse.config.ts. When the target is unset the tests
 * SKIP rather than testing the wrong environment.
 *
 * Run (from e2e/):
 *   PORTAL_BASE_URL=https://soymutdb.test/ \
 *     npx playwright test -c playwright-portal-embed.config.ts
 *
 * Discover without a browser:
 *   PORTAL_BASE_URL=https://soymutdb.test/ \
 *     npx playwright test -c playwright-portal-embed.config.ts --list
 */
const baseURL =
  process.env.PORTAL_BASE_URL ?? process.env.SMOKE_BASE_URL ?? "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "./tests",
  testMatch: /portal-browser-embed\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-portal-embed" }],
  ],
  use: {
    baseURL,
    // The embed chrome is English; pin locale so host detection cannot flip the
    // portal i18n and surprise the assertions.
    locale: "en-US",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-portal-embed",
});
