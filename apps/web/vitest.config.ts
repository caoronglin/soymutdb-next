import { fileURLToPath } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

// Keep legacy Vue component tests loadable while adding React TSX test coverage.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // Mirrors the `@/*` -> `src/*` path mapping in tsconfig.json so React
      // route/component tests can import the same `@/lib/antd` entry points as
      // the application instead of resorting to relative-import workarounds.
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "src/**/*.spec.ts", "src/**/*.spec.tsx"],
    pool: "forks",
    poolOptions: {
      forks: {
        singleFork: true,
        maxForks: 1,
      },
    },
  },
});
