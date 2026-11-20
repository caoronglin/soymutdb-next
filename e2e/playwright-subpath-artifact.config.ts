import { defineConfig } from "@playwright/test";

/**
 * Sub-path deployment gate. Served from a `build-pages-artifact.sh` tree, which
 * mounts the portal under `/soymutdb-next/` — the shape a gh-pages release has.
 *
 * Runs the SAME public specs as `playwright-public.config.ts` plus the three
 * base-path assertions in `tests/subpath-artifact.spec.ts`. Two things make that
 * work against a prefixed mount: `E2E_BASE_PATH` (which the sweep exports for
 * this gate) and the idempotent `withBasePath()` in `tests/helpers.ts`.
 *
 * `entity-detail` is deliberately absent: that spec resolves its own base from
 * `PORTAL_BASE_URL` and is already gate #5 of the sweep against its own server.
 *
 * Usage:  bash scripts/build-pages-artifact.sh
 *         npx playwright test -c playwright-subpath-artifact.config.ts
 */
const PORT = 4196;
const PREFIX = "/soymutdb-next";
const baseURL = `http://localhost:${PORT}${PREFIX}/`;

export default defineConfig({
  testDir: "./tests",
  testMatch:
    // `entity-detail` is deliberately absent: that spec resolves its own base from
    // `PORTAL_BASE_URL` and is already gate #5 of this sweep against its own
    // server, so running it here would test a second, differently-based target.
    /(subpath-artifact|homepage|search|genes|route-smoke|api-shape-resilience|downloads|seqfetch|accessibility|blast|public-login|seed-request|enrichment|exppattern|browser-bridge|expression-phenotype)\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-subpath-artifact" }],
  ],
  use: {
    baseURL,
    locale: "en-US",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-subpath-artifact",
  webServer: {
    // Serve the SUB-PATH artifact where the deployment publishes it.
    command: `node static-server.mjs ../pages-dist ${PORT} ${PREFIX}`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
