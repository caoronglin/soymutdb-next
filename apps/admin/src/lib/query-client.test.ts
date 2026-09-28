import { describe, expect, it } from "vitest";

import { ApiError } from "@soymutdb/api-client";

import { createQueryClient } from "./query-client";

/**
 * Regression guard for the React→Vue admin query-client parity: the Vue cutover
 * silently reverted to TanStack's defaults (staleTime 0, refetch-on-focus on,
 * three retries for every error), which turned an unreachable API into an
 * endless loading state and made every tab focus re-fetch.
 */
describe("createQueryClient", () => {
  const options = createQueryClient().getDefaultOptions();
  const queries = options.queries!;

  it("keeps the React stale/gc windows", () => {
    expect(queries.staleTime).toBe(30 * 1000);
    expect(queries.gcTime).toBe(5 * 60 * 1000);
  });

  it("does not refetch on window focus", () => {
    expect(queries.refetchOnWindowFocus).toBe(false);
  });

  it("does not retry client errors and retries other failures once", () => {
    const retry = queries.retry as (failureCount: number, error: unknown) => boolean;
    expect(retry(0, new ApiError("not found", 404))).toBe(false);
    expect(retry(0, new ApiError("unauthorized", 401))).toBe(false);
    expect(retry(0, new ApiError("boom", 500))).toBe(true);
    expect(retry(1, new ApiError("boom", 500))).toBe(false);
    expect(retry(0, new TypeError("network down"))).toBe(true);
  });

  it("never retries mutations", () => {
    expect(options.mutations?.retry).toBe(false);
  });
});
