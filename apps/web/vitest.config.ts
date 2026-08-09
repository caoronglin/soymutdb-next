import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["scripts/__tests__/**/*.test.{ts,tsx}"],
    // Node v26: forked pool with a single worker keeps the suite stable
    // (same pattern as packages/ui, packages/api-client and apps/admin).
    pool: "forks",
    maxWorkers: 1,
    css: false,
  },
});
