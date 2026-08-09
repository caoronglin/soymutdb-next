import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
    // Node v26: forked pool with a single worker keeps the suite stable
    // (same pattern as packages/ui and packages/api-client).
    pool: "forks",
    maxWorkers: 1,
    css: false,
  },
});
