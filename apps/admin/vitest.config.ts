import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
    // Node v26: a forked pool with one worker keeps DOM-heavy tests stable.
    pool: "forks",
    maxWorkers: 1,
    css: false,
  },
});
