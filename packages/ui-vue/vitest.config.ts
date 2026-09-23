import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

// Single-fork like the rest of the workspace (Node 24 pool teardown issue).
export default defineConfig({
  plugins: [vue()],
  test: {
    environment: "node",
    globals: true,
    include: ["src/**/*.test.ts"],
    pool: "forks",
    poolOptions: { forks: { singleFork: true, maxForks: 1 } },
  },
});
