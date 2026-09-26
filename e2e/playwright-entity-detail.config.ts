import { defineConfig } from "@playwright/test";

/**
 * Deployed-stack E2E for the entity detail pages: a mutant by public id, a
 * variant, and a gene.
 *
 * The three detail views answer only with real release data — a static mock
 * cannot prove the provenance chain — so this suite targets a deployed portal
 * with PORTAL_BASE_URL (or SMOKE_BASE_URL as a fallback). When the base is
 * unset every test SKIPS rather than testing the wrong environment.
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
const baseURL = (
  process.env.PORTAL_BASE_URL ??
  process.env.SMOKE_BASE_URL ??
  ""
).trim();

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
    baseURL: baseURL || undefined,
    // The detail catalog and test ids are English; pin the browser locale so
    // host detection cannot switch i18n and surprise the assertions.
    locale: "en-US",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-entity-detail",
});
