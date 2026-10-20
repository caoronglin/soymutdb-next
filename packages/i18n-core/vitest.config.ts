import { defineConfig } from "vitest/config";

// Framework-neutral locale core. detectLanguage touches browser globals only
// when a window exists, so the SSR-safe assertions run in the plain node
// environment without pulling in jsdom.
export default defineConfig({
  test: {
    environment: "node",
    globals: true,
    include: ["src/**/*.test.ts"],
    pool: "forks",
    // Vitest 5 removed `poolOptions`; one forked worker keeps the
    // suite serial (isolation stays on: files share global mocks otherwise).
    maxWorkers: 1,
      },
});
