import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

// Single-fork like the rest of the workspace (Node 24 pool teardown issue), and
// the Vue plugin so component tests can import .vue files.
export default defineConfig({
  plugins: [vue()],
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
