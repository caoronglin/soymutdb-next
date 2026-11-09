import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
// Vite 8 transforms with Oxc; the shared tsconfig keeps `"jsx": "preserve"`
// for the Umi build, which Oxc refuses to import in tests. Pin the automatic
// React runtime here instead of rewriting the application tsconfig.
  oxc: { jsx: { runtime: "automatic" } },
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
    // `src/test/setup.ts` holds the Node/jsdom compatibility shims (Web Storage,
    // ResizeObserver, matchMedia). Without this entry the file was never loaded,
    // so components that measure layout threw "ResizeObserver is not defined".
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "src/**/*.spec.ts", "src/**/*.spec.tsx"],
    pool: "forks",
    // Vitest 5 removed `poolOptions`; one forked worker keeps the
    // suite serial (isolation stays on: files share global mocks otherwise).
    maxWorkers: 1,
      },
});