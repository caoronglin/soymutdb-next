import { defineConfig } from "vitest/config";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  resolve: {
    // Keep test resolution aligned with Vite and tsconfig's @/* contract.
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "node",
    include: [
      "scripts/__tests__/**/*.test.{ts,tsx}",
      "src/**/__tests__/**/*.test.{ts,tsx}",
    ],
    // Node v26: forked pool with a single worker keeps the suite stable
    // (same pattern as the shared package suites and apps/admin).
    pool: "forks",
    maxWorkers: 1,
    css: false,
    // Initialise i18next and clean up the DOM between tests. Without this a
    // component that interpolates (`t(key, { defaultValue: "{{n}} rows" })`)
    // renders the literal template and its assertion fails for the wrong reason.
    setupFiles: ["./src/test/setup.ts"],
  },
});
