import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    pool: "forks",
    poolOptions: { forks: { singleFork: true, maxForks: 1 } },
  },
});
