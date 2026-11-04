import { defineConfig } from "@playwright/test";

/**
 * Local E2E for the Phase 4/8 public UI (homepage/search/genes/accessibility/
 * BLAST/login). Offline-capable where possible; the static server supplies
 * only the deterministic API mocks required by an interaction test.
 *
 * Requires a built dist (apps/web/dist) — the webServer starts
 * e2e/static-server.mjs which serves `apps/web/dist/external` at the origin
 * root (build:sites emits base-`/` artifacts) with SPA fallback. The portal ships no embedded fallback data: an unreachable API
 * produces an explicit empty or error state, never fabricated rows.
 *
 * Run from e2e/:  npx playwright test -c playwright-public.config.ts
 */
const baseURL = "http://localhost:4173/";

export default defineConfig({
  testDir: "./tests",
  testMatch:
    /(homepage|search|genes|accessibility|blast|public-login|route-smoke|api-shape-resilience|seed-request|downloads|seqfetch|exppattern|enrichment|browser-bridge|analyses|analyses-submit|expression-phenotype)\.spec\.ts/,
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
    // The specs assert the English catalog; pin the browser locale so the
    // portal's language detection cannot follow the host and render zh.
    locale: "en-US",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-public",
  webServer: {
    // Serve the external artifact explicitly. `build-sites.ts` writes the two
    // site variants to dist/external and dist/internal, so the dist root is a
    // stale single-site leftover rather than the portal under test. Mirrors
    // playwright-internal.config.ts, which already passes its own root.
    command: "node static-server.mjs ../apps/web/dist/external 4173 /",
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
