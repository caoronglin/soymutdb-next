import { defineConfig } from "@playwright/test";

/**
 * Deployed-stack E2E for the Admin console beyond the login form.
 *
 * Unlike `playwright-admin-production.config.ts` (which serves the offline
 * `apps/admin/dist` static artifact and stops at the login form), this config
 * targets a real deployment whose API/CORS/CSP are configured, so protected
 * routes can actually mount.
 *
 * Target the deployment with ADMIN_BASE_URL. Provide ADMIN_STORAGE_STATE (a
 * Playwright storage state captured from a real sign-in) to exercise the
 * authenticated routes; without either value the dependent tests SKIP rather
 * than testing the wrong environment.
 *
 * Run (from e2e/):
 *   ADMIN_BASE_URL=https://admin.soymutdb.test/ \
 *   ADMIN_STORAGE_STATE=/secure/admin-storage-state.json \
 *     npx playwright test -c playwright-admin-console.config.ts
 *
 * Discover without a browser:
 *   ADMIN_BASE_URL=https://admin.soymutdb.test/ \
 *     npx playwright test -c playwright-admin-console.config.ts --list
 */
const baseURL = process.env.ADMIN_BASE_URL;

export default defineConfig({
  testDir: "./tests",
  testMatch: /admin-console\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-admin-console" }],
  ],
  use: {
    baseURL,
    // The console is Chinese-first: `apps/admin/src/react-app.tsx` calls
    // `initI18n("zh")`, so the browser locale cannot switch the catalog. It is
    // pinned only to keep host detection deterministic across runs — every
    // assertion in the spec is a `data-testid`, never copy.
    locale: "en-US",
    storageState: process.env.ADMIN_STORAGE_STATE || undefined,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-admin-console",
});
