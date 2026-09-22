import { defineConfig } from "vitest/config";

// Node 24 breaks vitest's default threaded worker pool on teardown
// (tinypool "emitter.removeListener is not a function"). The workspace already
// runs single-forked children in packages/api-client; mirror that here so tests
// report results and exit cleanly on newer Node runtimes.
export default defineConfig({
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
