import { defineConfig } from "@playwright/test";

/**
 * Local E2E for the primer-design page (pure-frontend, offline).
 *
 * Requires a built dist — the webServer starts e2e/static-server.mjs serving
 * `apps/web/dist/external` at the origin root (build:sites emits base-`/`
 * artifacts), with an SPA fallback and a mocked /api/v1/tools/seqfetch
 * endpoint, so the "from genome" mode works without a backend.
 *
 * Run from e2e/:  npx playwright test -c playwright-primer.config.ts
 * No CI workflow currently runs this config; it is an offline local gate
 * (the default `playwright.config.ts` is the CI-wired online smoke). Run it
 * after `pnpm --filter @soymutdb/web build:sites`.
 */
const baseURL = "http://localhost:4173/";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/primer-design.spec.ts",
  workers: 1,
  fullyParallel: false,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-primer" }],
  ],
  use: {
    baseURL,
    // The spec asserts English copy; pin the locale so a zh host cannot flip
    // detectLanguage() and fail on translated text.
    locale: "en-US",
    // Route-reveal animations move the antd Select portal while Playwright is
    // resolving option positions; reduced motion makes the form geometry static
    // and the interaction deterministic.
    // `reducedMotion` is a browser-context option; the type surface accepts it
    // only under `contextOptions`, not as a top-level `use` key.
    contextOptions: { reducedMotion: "reduce" },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-primer",
  webServer: {
    command: "node static-server.mjs ../apps/web/dist/external 4173 /",
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
