// @vitest-environment node
//
// REGRESSION — the variants list query key must include the cursor position.
//
// Invariant: two pages of the same variants query (first page vs. a cursor page)
// occupy TWO distinct query-cache entries, and each entry reads back its own
// data; a cursor page must never silently reuse the first page's rows.
// Guards: the `queryKeys.variants.list` builder in @soymutdb/query-keys and every
// consumer (VariantsView) that pages through it.
// Source (ablation): docs/dev/ablation/2026-09-26/frontend.md §3 「P1-04 variants
// 游标键」row (GUARD-ACTIVE) and §6.C — removing `context.cursor ?? null` from
// packages/query-keys/src/index.ts flipped this harness to 2 failed | 1 passed.
// If this is RED: the cursor was dropped from (or moved within) the key builder,
// so page 2+ will render page 1's rows under an unchanged key. Fix the builder,
// not this test.
//
// CONTROL drives the REAL builder through a REAL TanStack QueryClient in-memory
// cache. The ABLATION case feeds the same builder `cursor: null` (the pre-P1-04
// shape) and proves collapsing the key erases the page boundary.
import { QueryClient } from "@tanstack/vue-query";
import { queryKeys } from "@soymutdb/query-keys";
import { describe, expect, it } from "vitest";

const BASE = {
  assemblyId: "5",
  releaseId: "2026.09",
  siteVariant: "external" as const,
  page: 1,
  chromosome: null,
  start: null,
  end: null,
  impact: null,
  variantType: null,
  mutantLinePublicId: null,
};

// Control: cursor participates in the key.
const realKey = (cursor: string | null) => queryKeys.variants.list({ ...BASE, cursor });
// Ablation: cursor neutralised (the key that existed before P1-04).
const noCursorKey = (_cursor: string | null) => queryKeys.variants.list({ ...BASE, cursor: null });

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
}

async function seed(client: QueryClient, keyFn: (cursor: string | null) => readonly unknown[]) {
  await client.fetchQuery({
    queryKey: keyFn(null) as unknown[],
    queryFn: async () => "first-page",
  });
  await client.fetchQuery({
    queryKey: keyFn("c2") as unknown[],
    queryFn: async () => "cursor-page",
  });
}

describe("ABLATION P1-04: variants list key includes the cursor position", () => {
  it("CONTROL: a cursor page gets its own key and its own cache entry", async () => {
    const client = newClient();
    await seed(client, realKey);

    // Distinct keys -> two distinct entries.
    expect(realKey(null)).not.toEqual(realKey("c2"));
    expect(client.getQueryCache().getAll()).toHaveLength(2);
    // Each entry reads its OWN data (cursor page does not read page one).
    expect(client.getQueryData(realKey(null) as unknown as unknown[])).toBe("first-page");
    expect(client.getQueryData(realKey("c2") as unknown as unknown[])).toBe("cursor-page");
  });

  it("ABLATION: dropping the cursor collapses both pages onto one entry", async () => {
    const client = newClient();
    await seed(client, noCursorKey);

    // Same key -> the second fetch is a cache hit.
    expect(noCursorKey(null)).toEqual(noCursorKey("c2"));
    expect(client.getQueryCache().getAll()).toHaveLength(1);
    // The cursor page now reads the FIRST page's rows.
    expect(client.getQueryData(noCursorKey(null) as unknown as unknown[])).toBe("first-page");
    expect(client.getQueryData(noCursorKey("c2") as unknown as unknown[])).toBe("first-page");
  });

  it("the real key differs from the cursor-less key (the fix is load-bearing)", () => {
    expect(realKey("c2")).not.toEqual(noCursorKey("c2"));
    // The cursor is present at a stable position in the real key.
    expect(realKey("c2")).toContain("c2");
  });
});
