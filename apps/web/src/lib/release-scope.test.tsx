/**
 * Runtime evidence for release switching.
 *
 * The previous state of this code had no observer at all: `getReleaseId()` was
 * a module variable read once per render, `applyDeploymentRelease()` had zero
 * callers, and nothing could react to a publish. These tests pin both halves:
 *
 * - a probe that finds a *different* active release drops exactly the
 *   release-scoped cache entries and re-runs the mounted queries;
 * - a probe that finds the *same* release, or that fails, leaves them alone.
 *
 * The second half keeps the mechanism honest: an invalidation firing on every
 * poll would turn a 60s timer into a cache-thrash loop.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@soymutdb/query-keys";

const transport = vi.hoisted(() => ({
  releaseId: "1" as string | null,
  activeReleaseId: "1" as string | null,
  probeFails: false,
  probes: 0,
  assemblyRuns: [] as Array<string | null>,
  newsRuns: 0,
  listeners: new Set<(next: string | null, previous: string | null) => void>(),
}));

vi.mock("@soymutdb/api-client", () => ({
  getReleaseId: () => transport.releaseId,
  setReleaseId: (value: string | null) => {
    const previous = transport.releaseId;
    transport.releaseId = value;
    if (value === previous) return;
    for (const listener of [...transport.listeners]) listener(value, previous);
  },
  subscribeToRelease: (listener: (next: string | null, previous: string | null) => void) => {
    transport.listeners.add(listener);
    return () => transport.listeners.delete(listener);
  },
  getActiveRelease: async () => {
    transport.probes += 1;
    if (transport.probeFails) throw new TypeError("Failed to fetch");
    return {
      release_id: transport.activeReleaseId,
      version: transport.activeReleaseId ? `2026.${transport.activeReleaseId}` : null,
      published_at: null,
    };
  },
}));

import {
  RELEASE_SCOPED_PREFIXES,
  ReleaseScopeProvider,
  dropReleaseScopedQueries,
  isReleaseScopedKey,
  useReleaseScope,
} from "./release-scope";

function Probe() {
  const { releaseId, switchCount, refresh } = useReleaseScope();
  const assemblies = useQuery({
    queryKey: queryKeys.assemblies.list({ releaseId, siteVariant: "external" }),
    queryFn: async () => {
      transport.assemblyRuns.push(releaseId);
      return [{ id: Number(releaseId ?? 0), name: `release-${releaseId}` }];
    },
    staleTime: 60_000,
  });
  const news = useQuery({
    queryKey: queryKeys.news.list({ category: null, page: 1, pageSize: 10 }),
    queryFn: async () => {
      transport.newsRuns += 1;
      return ["not release scoped"];
    },
    staleTime: 60_000,
  });
  return (
    <div>
      <span data-testid="release">{releaseId ?? "active"}</span>
      <span data-testid="switches">{switchCount}</span>
      <span data-testid="assembly">{assemblies.data?.[0]?.name ?? "-"}</span>
      <span data-testid="news">{news.data?.[0] ?? "-"}</span>
      <button type="button" onClick={() => void refresh()}>
        probe
      </button>
    </div>
  );
}

async function renderScope() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={queryClient}>
      <ReleaseScopeProvider queryClient={queryClient} pollMs={0}>
        <Probe />
      </ReleaseScopeProvider>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByTestId("assembly").textContent).toBe("release-1"));
  return { queryClient, user };
}

beforeEach(() => {
  transport.releaseId = "1";
  transport.activeReleaseId = "1";
  transport.probeFails = false;
  transport.probes = 0;
  transport.assemblyRuns = [];
  transport.newsRuns = 0;
  transport.listeners.clear();
});

afterEach(() => {
  cleanup();
});

describe("release-scoped key classification", () => {
  it("recognises every declared family", () => {
    for (const prefix of RELEASE_SCOPED_PREFIXES) {
      expect(isReleaseScopedKey([...prefix, "release", "external"])).toBe(true);
    }
  });

  it("leaves release-independent caches alone", () => {
    expect(isReleaseScopedKey(queryKeys.news.list({ category: null, page: 1, pageSize: 10 }))).toBe(false);
    expect(isReleaseScopedKey(queryKeys.news.detail("a-slug"))).toBe(false);
    expect(isReleaseScopedKey(["table-views", "gene", "Glycine max", "external"])).toBe(false);
    expect(isReleaseScopedKey(["downloads", "genome"])).toBe(false);
  });

  it("does not mistake an unrelated key for a family prefix", () => {
    expect(isReleaseScopedKey(["soymutdb", "news", "list", null, 1, 10])).toBe(false);
  });
});

describe("release switching", () => {
  it("drops release-scoped caches and refetches when the active release moves", async () => {
    const { user, queryClient } = await renderScope();
    expect(screen.getByTestId("news").textContent).toBe("not release scoped");

    // An operator publishes release 2 while the tab is open; the next probe sees it.
    transport.activeReleaseId = "2";
    await user.click(screen.getByRole("button", { name: "probe" }));

    await waitFor(() => expect(screen.getByTestId("release").textContent).toBe("2"));
    await waitFor(() => expect(screen.getByTestId("assembly").textContent).toBe("release-2"));
    expect(screen.getByTestId("switches").textContent).toBe("1");

    // The old release's cache entry is gone, so nothing can read stale data.
    expect(queryClient.getQueryData(queryKeys.assemblies.list({ releaseId: "1", siteVariant: "external" }))).toBeUndefined();
    expect(queryClient.getQueryData(queryKeys.assemblies.list({ releaseId: "2", siteVariant: "external" }))).toBeTruthy();
    // The news query is not release-scoped: it must not have been refetched.
    expect(transport.newsRuns).toBe(1);
  });

  it("leaves the cache alone when the probe reports the same release", async () => {
    const { queryClient, user } = await renderScope();
    const before = queryClient.getQueryData(queryKeys.assemblies.list({ releaseId: "1", siteVariant: "external" }));

    await user.click(screen.getByRole("button", { name: "probe" }));
    await waitFor(() => expect(transport.probes).toBeGreaterThan(1));

    expect(queryClient.getQueryData(queryKeys.assemblies.list({ releaseId: "1", siteVariant: "external" }))).toBe(before);
    expect(screen.getByTestId("switches").textContent).toBe("0");
    expect(transport.assemblyRuns).toEqual(["1"]);
  });

  it("keeps the current pin when the probe fails", async () => {
    const { queryClient, user } = await renderScope();
    transport.probeFails = true;

    await user.click(screen.getByRole("button", { name: "probe" }));

    expect(screen.getByTestId("release").textContent).toBe("1");
    expect(screen.getByTestId("switches").textContent).toBe("0");
    expect(queryClient.getQueryData(queryKeys.assemblies.list({ releaseId: "1", siteVariant: "external" }))).toBeTruthy();
  });

  it("dropReleaseScopedQueries removes only the scoped entries", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.assemblies.list({ releaseId: "1", siteVariant: "external" }), ["a"]);
    queryClient.setQueryData(queryKeys.news.list({ category: null, page: 1, pageSize: 10 }), ["n"]);
    queryClient.setQueryData(["analytics", "impact", "1", "external"], { ok: true });

    const dropped = dropReleaseScopedQueries(queryClient);

    expect(dropped).toHaveLength(2);
    expect(queryClient.getQueryData(queryKeys.assemblies.list({ releaseId: "1", siteVariant: "external" }))).toBeUndefined();
    expect(queryClient.getQueryData(["analytics", "impact", "1", "external"])).toBeUndefined();
    expect(queryClient.getQueryData(queryKeys.news.list({ category: null, page: 1, pageSize: 10 }))).toEqual(["n"]);
  });
});