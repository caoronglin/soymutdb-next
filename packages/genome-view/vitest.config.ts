import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

// Component tests need a DOM; pure viewport/registry tests are unaffected.
export default defineConfig({
  plugins: [vue()],
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.ts"],
    passWithNoTests: true,
    pool: "forks",
    poolOptions: { forks: { singleFork: true, maxForks: 1 } },
  },
});
