import { defineConfig } from "vitest/config";

// Pure, dependency-free view-model logic; node environment is sufficient.
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
