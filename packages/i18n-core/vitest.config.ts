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
    poolOptions: {
      forks: {
        singleFork: true,
        maxForks: 1,
      },
    },
  },
});
