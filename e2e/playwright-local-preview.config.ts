import { defineConfig } from "@playwright/test";

// Explicit local integration suite: requires an existing preview API + UI.
// Never import this config from the online GitHub Pages smoke workflow.
export default defineConfig({
  testDir: "./tests",
  testMatch: "**/local-preview.spec.ts",
  workers: 1,
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: process.env.LOCAL_PREVIEW_BASE_URL ?? "http://127.0.0.1:5173/",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  outputDir: "test-results-local-preview",
});
