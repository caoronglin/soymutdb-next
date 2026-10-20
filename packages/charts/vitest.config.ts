import { defineConfig } from "vitest/config";

// Vite 8 transforms with Oxc instead of esbuild. The shared tsconfig keeps
// `"jsx": "preserve"` for the Umi/Babel application build, which Oxc refuses to
// import in tests, so pin the automatic runtime here (React 19 has no global
// React binding and the components import React as a type only).
export default defineConfig({
  oxc: { jsx: { runtime: "automatic" } },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    pool: "forks",

    maxWorkers: 1,

      },
});
