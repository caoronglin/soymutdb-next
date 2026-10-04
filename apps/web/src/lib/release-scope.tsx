/**
 * Runtime release scope for the portal.
 *
 * ## Why this exists
 *
 * The release is pinned at build time (`VITE_SOYMUTDB_RELEASE_ID`) and read
 * through `getReleaseId()`, which is a plain module variable. A long-lived tab
 * therefore kept asking for the release it was built with after an operator
 * published a new one, and nothing in the app could notice: the switch had no
 * observer at all. Shortening `staleTime` would not fix that — the cached entry
 * would still belong to the old release — so the invalidation has to be driven
 * by an actual change of the pinned id.
 *
 * ## Ownership
 *
 * `api-client` owns the pin and notifies subscribers. This module owns the
 * React half: it learns when the pin changed, tells React, and drops the
 * caches whose identity is release-bound. It does not re-pin anything on its
 * own — a deployment that pins nothing keeps following the server default,
 * which is the documented behaviour for an unpinned site.
 *
 * ## What is dropped
 *
 * Only queries whose key carries a release. A blanket `invalidateQueries()`
 * would refetch public content and personal data that the switch does not
 * affect; `releaseScopedKeys()` below is the predicate both this module and its
 * tests use, so the two cannot drift.
 */
import * as React from "react";
import { QueryClient } from "@tanstack/react-query";
import {
  getActiveRelease,
  getReleaseId,
  setReleaseId,
  subscribeToRelease,
} from "@soymutdb/api-client";
import { queryKeys } from "@soymutdb/query-keys";

/** How often to ask the server whether the active release moved. */
export const RELEASE_POLL_MS = 60_000;

/**
 * Cache-key prefixes whose identity is bound to a release.
 *
 * Declared rather than sniffed: a key's release slot sits in a different
 * position per family (`assemblies.list` is `[..., "list", release, site]`,
 * `discoveryTrend` is `[..., days, release, site]`), and two structurally
 * identical prefixes (`news`, `table-views`) carry no release at all. A
 * structural guess would either miss families or drop caches the switch does
 * not affect, so the list is explicit and
 * `release-scope.test.ts` fails if a family drifts out of it.
 *
 * `queryKeys` owns the shared families; the `analytics` / `gene-search` /
 * `search-region` roots are app-local keys in `lib/query-options.ts`.
 */
export const RELEASE_SCOPED_PREFIXES: ReadonlyArray<readonly unknown[]> = [
  queryKeys.assemblies.all(),
  queryKeys.genes.all(),
  queryKeys.search.all(),
  queryKeys.mutants.all(),
  queryKeys.variants.all(),
  ["analytics"],
  ["gene-search"],
  ["search-region"],
];

/** True when a cache key belongs to a release-scoped family. */
export function isReleaseScopedKey(queryKey: readonly unknown[]): boolean {
  return RELEASE_SCOPED_PREFIXES.some((prefix) =>
    prefix.every((part, index) => queryKey[index] === part),
  );
}

export interface ReleaseScopeValue {
  /** The release currently pinned for this tab, or null when following the server. */
  releaseId: string | null;
  /** True once the first probe answered, so the UI can tell "unknown" from "unset". */
  probed: boolean;
  /** Switches applied in this page load (0 = the build-time pin still holds). */
  switchCount: number;
  /** Force a probe now, e.g. from a manual "reload data" affordance. */
  refresh: () => Promise<void>;
}

const ReleaseScopeContext = React.createContext<ReleaseScopeValue | null>(null);

export function useReleaseScope(): ReleaseScopeValue {
  const value = React.useContext(ReleaseScopeContext);
  if (!value) throw new Error("useReleaseScope must be used inside <ReleaseScopeProvider>");
  return value;
}

/**
 * The release to key a query with, as React state.
 *
 * Returns the same value as `getReleaseId()`, but re-renders when it changes.
 * A view that called `getReleaseId()` during render captured a snapshot that
 * no change could invalidate.
 */
export function useReleaseId(): string | null {
  return useReleaseScope().releaseId;
}

/** Drop every cached entry whose identity is bound to a release. */
export function dropReleaseScopedQueries(queryClient: QueryClient): string[] {
  const dropped: string[] = [];
  for (const query of queryClient.getQueryCache().getAll()) {
    if (!isReleaseScopedKey(query.queryKey)) continue;
    dropped.push(JSON.stringify(query.queryKey));
    queryClient.removeQueries({ queryKey: query.queryKey, exact: true });
  }
  return dropped;
}

export interface ReleaseScopeProviderProps {
  children: React.ReactNode;
  queryClient: QueryClient;
  /** Injected in tests; defaults to the real transport. */
  readActiveRelease?: typeof getActiveRelease;
  pollMs?: number;
}

export function ReleaseScopeProvider({
  children,
  queryClient,
  readActiveRelease = getActiveRelease,
  pollMs = RELEASE_POLL_MS,
}: ReleaseScopeProviderProps): React.ReactElement {
  const [releaseId, setRelease] = React.useState<string | null>(() => getReleaseId());
  const [probed, setProbed] = React.useState(false);
  const [switchCount, setSwitchCount] = React.useState(0);
  const mounted = React.useRef(true);

  React.useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // The transport owns the pin; react to its changes instead of re-reading it.
  React.useEffect(
    () =>
      subscribeToRelease((next) => {
        if (!mounted.current) return;
        setRelease(next);
        setSwitchCount((count) => count + 1);
        dropReleaseScopedQueries(queryClient);
        // Only the release-scoped families re-run. A blanket `refetchQueries()`
        // would also refetch public news and personal data that the switch
        // does not affect — which is what the first version of this code did,
        // and what this predicate exists to prevent.
        void queryClient.refetchQueries({
          predicate: (query) => isReleaseScopedKey(query.queryKey),
          type: "active",
        });
      }),
    [queryClient],
  );

  const refresh = React.useCallback(async () => {
    try {
      const active = await readActiveRelease();
      if (!mounted.current) return;
      setProbed(true);
      const next = active.release_id;
      // `setReleaseId` is a no-op when the id is unchanged, so a poll that finds
      // the same release does not throw the cache away.
      setReleaseId(next);
      if (!next) setRelease(null);
    } catch {
      // A probe failure is not a release change: keep the current pin and stay
      // quiet rather than showing a switch that did not happen.
      if (mounted.current) setProbed(true);
    }
  }, [readActiveRelease]);

  React.useEffect(() => {
    void refresh();
    if (pollMs <= 0 || typeof window === "undefined") return;
    const timer = window.setInterval(() => void refresh(), pollMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh, pollMs]);

  const value = React.useMemo<ReleaseScopeValue>(
    () => ({ releaseId, probed, switchCount, refresh }),
    [releaseId, probed, switchCount, refresh],
  );

  return <ReleaseScopeContext.Provider value={value}>{children}</ReleaseScopeContext.Provider>;
}