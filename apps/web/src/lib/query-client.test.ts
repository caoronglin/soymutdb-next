import { describe, expect, it } from "vitest";

import { ApiError } from "@soymutdb/api-client";

import { createQueryClient } from "./query-client";

/**
 * Regression guard for the React→Vue query-client parity: the Vue cutover
 * silently reverted to TanStack's defaults (staleTime 0, refetch-on-focus on,
 * three retries for every error), which made an unreachable API look like an
 * endless loading state instead of the page's error state.
 */
describe("createQueryClient", () => {
  const options = createQueryClient().getDefaultOptions();
  const queries = options.queries!;

  it("keeps the React stale/gc windows", () => {
    expect(queries.staleTime).toBe(5 * 60 * 1000);
    expect(queries.gcTime).toBe(30 * 60 * 1000);
  });

  it("does not refetch on window focus", () => {
    expect(queries.refetchOnWindowFocus).toBe(false);
  });

  it("backs off with a bounded delay", () => {
    const retryDelay = queries.retryDelay as (attempt: number) => number;
    expect(retryDelay(0)).toBe(1000);
    expect(retryDelay(1)).toBe(2000);
    expect(retryDelay(4)).toBe(8000);
  });

  it("does not retry client errors and retries server errors twice", () => {
    const retry = queries.retry as (failureCount: number, error: unknown) => boolean;
    expect(retry(0, new ApiError("not found", 404))).toBe(false);
    expect(retry(0, new ApiError("unauthorized", 401))).toBe(false);
    expect(retry(0, new ApiError("boom", 500))).toBe(true);
    expect(retry(1, new ApiError("boom", 500))).toBe(true);
    expect(retry(2, new ApiError("boom", 500))).toBe(false);
    expect(retry(0, new TypeError("network down"))).toBe(true);
  });

  it("never retries mutations", () => {
    expect(options.mutations?.retry).toBe(false);
  });
});
