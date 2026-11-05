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

    // A default 5s budget measures the wrong thing on this box. A dialog test
    // here mounts the real antd Modal plus a React Query tree, and CI runs the
    // whole workspace suite in ONE foreground turbo process: the admin, web and
    // charts vitest runs (each forking workers) and their builds all compete
    // for one cgroup's cores. The wall clock that remains is contention, so a
    // green suite could still fail here — real build cnb-mdm-1k6kma6fv did
    // exactly that on `starts one upload for two clicks in the same tick`
    // (5241ms against a 5000ms default) while the other three cases in the same
    // file passed.
    //
    // The regression that test protects is a second upload firing in the same
    // tick, which is a SYNCHRONOUS invariant: `waitFor` reaches it in
    // milliseconds once the event loop is free. Raising the budget therefore
    // does not soften the assertion, it only stops the contention from being
    // reported as a defect. The hook budget stays at the default: a setup that
    // needs 30s is a hung module, not a busy CPU.
    testTimeout: 30_000,

      },
});
