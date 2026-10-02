import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
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
    poolOptions: {
      forks: {
        singleFork: true,
        maxForks: 1,
      },
    },
  },
});
