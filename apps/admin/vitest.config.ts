import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
// Vite 8 transforms with Oxc; the shared tsconfig keeps `"jsx": "preserve"`
// for the Umi build, which Oxc refuses to import in tests. Pin the automatic
// React runtime here instead of rewriting the application tsconfig.
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "src/**/*.spec.ts", "src/**/*.spec.tsx"],
    pool: "forks",

    maxWorkers: 1,

      },
});
