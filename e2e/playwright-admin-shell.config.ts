import { defineConfig } from "@playwright/test";

/**
 * Offline artifact gate for the AUTHENTICATED admin shell.
 *
 * `playwright-admin-production.config.ts` stops at the login form; the deployed
 * `playwright-admin-console.config.ts` needs a real console plus a signed-in
 * storage state, so nothing exercised the shell that operators actually use
 * (its sidebar/header/routes rotted before — see the admin-console spec's
 * history). This gate signs in through the real login form against the repo
 * static server's mocked auth endpoint and asserts the authenticated chrome
 * mounts without a crash.
 *
 * Run from e2e/:  npx playwright test -c playwright-admin-shell.config.ts
 */
const baseURL = "http://localhost:4189/";

export default defineConfig({
  testDir: "./tests",
  // Two specs share this gate: the mount sweep, and the write path that
  // actually changes the live site (navigation save, conflict handling).
  testMatch: /admin-(shell|write-paths)\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-admin-shell" }],
  ],
  use: {
    baseURL,
    // The console is Chinese-first in this build; assertions are testid-based.
    locale: "en-US",
    // `reducedMotion` is a browser-context option; the type surface accepts it
    // only under `contextOptions`, not as a top-level `use` key.
    contextOptions: { reducedMotion: "reduce" },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-admin-shell",
  webServer: {
    command: "node static-server.mjs ../apps/admin/dist 4189 /",
    url: baseURL,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
