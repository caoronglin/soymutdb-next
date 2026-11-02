import { defineConfig } from "vitest/config";

// The query keys are framework-neutral plain data (consumed by both TanStack
// React Query and TanStack Vue Query). The suite pins their exact cache-key
// shape so a React-side refactor cannot silently drift the shared contract.
export default defineConfig({
  test: {
    environment: "node",
    globals: true,
    include: ["src/**/*.test.ts"],
    pool: "forks",
    // Vitest 5 removed `poolOptions`; one forked worker keeps the
    // suite serial (isolation stays on: files share global mocks otherwise).
    maxWorkers: 1,
      },
});
