import { defineConfig } from "@playwright/test";

/**
 * Offline artifact gate for the standalone genome browser.
 *
 * Serves the built `apps/jbrowse/dist` at the origin root with the repository's
 * static server. Every deployment serves this app from its own origin root, so
 * the artifact's root-absolute asset/font URLs are exercised exactly as shipped.
 *
 * The API is not available here, so the gate asserts the *degraded* contract:
 * the shell boots (React handoff), the page reaches the "unable to load" alert
 * instead of crashing, and the split HarmonyOS faces that the CSS declares are
 * served with the right MIME. Full genome-browser behaviour needs a deployed
 * stack (`playwright-jbrowse.config.ts`).
 *
 * Run from e2e/:  npx playwright test -c playwright-jbrowse-artifact.config.ts
 */
const baseURL = "http://localhost:4186/";

export default defineConfig({
  testDir: "./tests",
  testMatch: /jbrowse-artifact\.spec\.ts/,
  workers: 1,
  fullyParallel: false,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-jbrowse-artifact" }],
  ],
  use: {
    baseURL,
    locale: "en-US",
    // `reducedMotion` is a browser-context option; the type surface accepts it
    // only under `contextOptions`, not as a top-level `use` key.
    contextOptions: { reducedMotion: "reduce" },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  outputDir: "test-results-jbrowse-artifact",
  webServer: {
    command: "node static-server.mjs ../apps/jbrowse/dist 4186 /",
    url: baseURL,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
