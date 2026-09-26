import { defineConfig } from "@playwright/test";

/**
 * Dedicated E2E config for the INTERNAL site variant.
 *
 * The two site variants are separate build/deployment boundaries with separate
 * base paths: the public artifact is served under /soymutdb-next (or a
 * configured public base), while the internal artifact is served at the origin
 * root /. Running the public suite against internal therefore fails with
 * "No route for /soymutdb-next/login" — this config exists so internal has its
 * own base and its own spec.
 *
 * Target the internal deployment with INTERNAL_BASE_URL (e.g.
 * https://internal.soymutdb.test/). When it is unset every test SKIPS rather
 * than testing the wrong environment.
 *
 * Run (from e2e/):
 *   INTERNAL_BASE_URL=https://internal.soymutdb.test/ \
 *     npx playwright test -c playwright-internal.config.ts
 *
 * Discover without a browser:
 *   npx playwright test -c playwright-internal.config.ts --list
 */
const baseURL = (process.env.INTERNAL_BASE_URL ?? "").trim();

export default defineConfig({
  testDir: "./tests",
  testMatch: /internal-site\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 20_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-internal" }],
  ],
  use: {
    baseURL: baseURL || undefined,
    // The internal catalog and test ids are English; pin the browser locale so
    // host detection cannot switch i18n and surprise the assertions.
    locale: "en-US",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-internal",
});
