import { defineConfig } from "vitest/config";

// Pure, dependency-free view-model logic; node environment is sufficient.
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
