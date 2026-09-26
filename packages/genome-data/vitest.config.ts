import { defineConfig } from "vitest/config";

// Framework-neutral data layer: node environment, no DOM required.
export default defineConfig({
  test: {
    environment: "node",
    globals: true,
    include: ["src/**/*.test.ts"],
    pool: "forks",
    poolOptions: { forks: { singleFork: true, maxForks: 1 } },
  },
});
