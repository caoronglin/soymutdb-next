// REGRESSION — the export lifecycle tests must wait for rendered state.
//
// Build cnb-8gf-1k6h565k1 failed Frontend verification with one flaky case:
// `submits an export and then tracks the submitted record` read
// `variant-export-status` via `getByTestId` right after
// `waitFor(() => expect(createVariantExport).toHaveBeenCalledTimes(1))`.
// The status line is rendered from the *resolved* response (see
// `useVariantExport.requestExport`: `setSubmitState` runs after the `await`),
// so a synchronous read loses a microtask on a slow runner.
//
// `waitFor(called)` proves the click dispatched the request, not that the
// response was applied. This source-level guard complements the deterministic
// late-response case in `export-flow.test.tsx`: the behavioral test catches a
// timing regression on the runner, while this one refuses a `findBy` → `getBy`
// edit before it ever reaches CI.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Vitest runs this suite from `apps/web`; `process.cwd()` is that package root.
const source = readFileSync(
  join(process.cwd(), "src/routes/variants/export-flow.test.tsx"),
  "utf8",
);

// Testids whose DOM is produced by `setExportId`/`setSubmitState` after the
// awaited response, plus the download/error surfaces reached the same way.
const POST_RESPONSE_TESTIDS = [
  "variant-export-status",
  "variant-export-progress",
  "variant-export-download",
  "variant-export-error",
];

describe("export lifecycle test assertions", () => {
  it.each(POST_RESPONSE_TESTIDS)(
    "waits for %s with a findBy query, never a synchronous getBy",
    (testid) => {
      expect(source).not.toMatch(
        new RegExp(`getByTestId\\(["'\`]${testid}["'\`]\\)`),
      );
      expect(source).toMatch(
        new RegExp(`findByTestId\\(["'\`]${testid}["'\`]\\)`),
      );
    },
  );
});
