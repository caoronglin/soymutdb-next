import { defineConfig } from "@playwright/test";

/**
 * Deployed-stack E2E for the entity detail pages: a mutant by public id, a
 * variant, and a gene.
 *
 * The three detail views answer only with real release data — a static mock
 * cannot prove the provenance chain — so this suite targets a deployed portal
 * with PORTAL_BASE_URL (or SMOKE_BASE_URL as a fallback). When neither is set
 * it falls back to the built public artifact served locally, with the spec's
 * deterministic API mocks; it never tests the wrong environment silently.
 *
 * Entity identifiers are taken from the target's own lists (mutants / variants
 * / genes) or supplied explicitly through ENTITY_MUTANT_PUBLIC_ID,
 * ENTITY_VARIANT_ID and ENTITY_GENE_ID. The suite never invents identifiers and
 * never uses credentials.
 *
 * Run (from e2e/):
 *   PORTAL_BASE_URL=https://soymutdb.test/ \
 *     npx playwright test -c playwright-entity-detail.config.ts
 *
 * Discover without a browser:
 *   PORTAL_BASE_URL=https://soymutdb.test/ \
 *     npx playwright test -c playwright-entity-detail.config.ts --list
 */
/**
 * Offline default target: the built public artifact served by the repo's own
 * static server (same recipe as playwright-public.config.ts). It lets this
 * suite run with no deployed stack; the spec installs deterministic API mocks
 * when no explicit base was supplied.
 */
const OFFLINE_BASE = "http://localhost:4176/soymutdb-next/";

const explicitBase = (
  process.env.PORTAL_BASE_URL ??
  process.env.SMOKE_BASE_URL ??
  ""
).trim();

const baseURL = explicitBase || OFFLINE_BASE;

export default defineConfig({
  testDir: "./tests",
  testMatch: /entity-detail\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 20_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-entity-detail" }],
  ],
  use: {
    baseURL,
    // The detail catalog and test ids are English; pin the browser locale so
    // host detection cannot switch i18n and surprise the assertions.
    locale: "en-US",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-entity-detail",
  webServer: explicitBase
    ? undefined
    : {
        command: "node static-server.mjs ../apps/web/dist 4176 /soymutdb-next",
        url: OFFLINE_BASE,
        reuseExistingServer: !process.env.CI,
        timeout: 30_000,
      },
});
