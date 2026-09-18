import { defineConfig } from "vitest/config";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  // Mirror the build-time constants declared in `vite.config.ts`. Without them
  // any module that branches on the site variant (e.g. `src/lib/site-content.tsx`)
  // throws `__SOYMUTDB_INTERNAL_SITE__ is not defined` under test.
  define: {
    __SOYMUTDB_INTERNAL_SITE__: false,
  },
  resolve: {
    // Keep test resolution aligned with Vite and tsconfig's @/* contract.
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "node",
    // Rebinds jsdom's localStorage on Node 25+, where Node's own experimental
    // global shadows it and leaves the value `undefined`. See the file header
    // for the measured behaviour and the removal condition.
    setupFiles: ["./src/test/setup.ts"],
    include: [
      "scripts/__tests__/**/*.test.{ts,tsx}",
      "src/**/__tests__/**/*.test.{ts,tsx}",
    ],
    // Node v26: forked pool with a single worker keeps the suite stable
    // (same pattern as the shared package suites and apps/admin).
    pool: "forks",
    maxWorkers: 1,
    css: false,
  },
});
