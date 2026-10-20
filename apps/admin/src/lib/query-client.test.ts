import { describe, expect, it } from "vitest";

import { ApiError } from "@soymutdb/api-client";
import { CancelledError } from "@tanstack/react-query";

import { clearAdminSessionCache, createQueryClient } from "./query-client";

/** A promise whose settlement the test controls. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

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

/**
 * Session-boundary regressions for the cache. `staleTime` is 30s, so an entry
 * fetched as one operator is served to the next operator without a refetch:
 * the cache is only ever reset deliberately, at an identity transition.
 */
describe("clearAdminSessionCache", () => {
  it("drops every cached query, including one still in flight", async () => {
    const client = createQueryClient();
    client.setQueryData(["admin", "audit"], [{ id: 1 }]);
    client.setQueryData(["admin", "settings"], { theme: "dark" });

    const inFlight = deferred<string[]>();
    const pending = client.fetchQuery({
      queryKey: ["admin", "rows"],
      queryFn: () => inFlight.promise,
      retry: false,
    });
    const cancelled = pending.then(
      () => "resolved",
      (err: unknown) => err,
    );

    clearAdminSessionCache(client);

    expect(client.getQueryData(["admin", "audit"])).toBeUndefined();
    expect(client.getQueryData(["admin", "settings"])).toBeUndefined();

    // Clearing removes the query, and Query#destroy cancels its pending fetch,
    // so a response issued before the boundary is discarded rather than
    // delivered and written back into the emptied cache.
    const outcome = await cancelled;
    expect(outcome).toBeInstanceOf(CancelledError);

    inFlight.resolve(["stale-row"]);
    await Promise.resolve();
    expect(client.getQueryData(["admin", "rows"])).toBeUndefined();
    expect(client.getQueryCache().getAll()).toHaveLength(0);
  });

  it("is idempotent and tolerates an already-empty cache", () => {
    const client = createQueryClient();
    clearAdminSessionCache(client);
    clearAdminSessionCache(client);
    expect(client.getQueryCache().getAll()).toHaveLength(0);
  });

  it("is a no-op when no query client is mounted", () => {
    expect(() => clearAdminSessionCache(null)).not.toThrow();
    expect(() => clearAdminSessionCache(undefined)).not.toThrow();
  });
});
