import { defineConfig } from "@playwright/test";

/**
 * SoyMutDB online smoke tests — deployed gh-pages site.
 *
 * Target:  https://caoronglin.github.io/soymutdb-next/
 * Override with SMOKE_BASE_URL (e.g. a local static server serving dist/
 * for offline verification: SMOKE_BASE_URL=http://localhost:4173 ...).
 *
 * Network-fragility design (the site is on GitHub Pages, tests hit the
 * public internet):
 *   - workers=1: never run pages in parallel — a congested connection
 *     would cascade into false failures across parallel workers.
 *   - retries=1: transient connection resets are retried once before a
 *     test is reported as failed.
 *   - timeout=60s per test: SSG + hydration + failing API calls
 *     (placeholder origins) can take a while on a slow network.
 */
const siteBase = new URL(
  process.env.SMOKE_BASE_URL ?? "https://caoronglin.github.io/soymutdb-next/",
);
if (!siteBase.pathname.endsWith("/")) siteBase.pathname += "/";
if (siteBase.search || siteBase.hash) {
  throw new Error("SMOKE_BASE_URL must be a site base without query or fragment");
}
const rl_baseURL = siteBase.toString();

export default defineConfig({
  testDir: "./tests",
  // This config runs against the deployed public site only.  Local artifact
  // suites (including the Primer mock-server tests) use their own configs.
  testMatch: "**/online-smoke.spec.ts",
  // Single worker: fragile network, avoid concurrent false failures.
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 1,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  use: {
    baseURL: rl_baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results",
});
