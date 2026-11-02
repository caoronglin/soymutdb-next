import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // The sandbox reports fork/thread limits intermittently; a single fork per
    // run keeps the shared-package suite deterministic under `pnpm test`.
    pool: "forks",

    maxWorkers: 1,

      },
});
