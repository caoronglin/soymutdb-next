import { defineConfig } from "vitest/config";

// The viewport/registry/ruler tests are pure, and the SVG renderer is a pure
// function too, so nothing here needs a component runtime. jsdom is still used
// because the interactive component tests touch ResizeObserver.
export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    passWithNoTests: true,
    pool: "forks",

    maxWorkers: 1,

      },
});
