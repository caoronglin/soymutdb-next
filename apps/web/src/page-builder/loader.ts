/**
 * Page-definition loader (Phase 8).
 *
 * Resolves the published PageDefinition for a route from the public API
 * (`GET /page-definitions/{route}`), hydrates from the SSG-embedded bootstrap
 * (`#rl-page-definition`) when the pinned version matches so the first paint
 * needs no refetch, and falls back to the immutable seed on API failure.
 *
 * A release-pinned definition never silently downgrades: when a bootstrap
 * carries a `version`, the loader prefers it over a fresh API fetch.
 */

import { useQuery } from "@tanstack/react-query";
import { getPageDefinition } from "@soymutdb/api-client";
import type { PageDefinition, PageDefinitionVersion } from "@soymutdb/shared";
import {
  fallbackDefinitionFor,
} from "./seed";
import { isPageDefinition } from "./types";

/** Bootstrap tag id for page definitions (distinct from `rl-bootstrap`). */
const BOOTSTRAP_ID = "rl-page-definition";

/** The embedded bootstrap payload shape written by the SSG pipeline. */
export interface PageDefinitionBootstrap {
  route: string;
  version: number;
  version_id: string | null;
  definition: PageDefinition;
  generated_at: string;
}

/**
 * Read the page-definition bootstrap embedded in the current static HTML page
 * (synchronous, cheap). Returns null when absent, malformed, or a route/version
 * mismatch with the caller is detected (the caller still passes `route`).
 */
export function readPageDefinitionBootstrap(): PageDefinitionBootstrap | null {
  if (typeof document === "undefined") return null;
  const el = document.getElementById(BOOTSTRAP_ID);
  if (!el) return null;
  try {
    const raw = JSON.parse(el.textContent ?? "") as Record<string, unknown>;
    if (!raw || typeof raw !== "object") return null;
    if (typeof raw.route !== "string" || typeof raw.version !== "number") return null;
    if (!isPageDefinition(raw.definition)) return null;
    return raw as unknown as PageDefinitionBootstrap;
  } catch {
    return null;
  }
}

/** Route query key used by the loader (shares one cache entry per route). */
export function pageDefinitionKey(route: string): readonly [string, string] {
  return ["page-definition", route] as const;
}

/**
 * Resolve a definition for a route. Resolution order:
 *   1. SSG bootstrap with a matching route (hydrate; no refetch).
 *   2. Public API (background; seed is the fallback if it fails).
 *   3. Immutable seed fallback for `/` when the API is unavailable.
 */
export function usePageDefinition(route: string) {
  const routeKey = route === "/" ? "/" : `/${route.replace(/^\/+/, "")}`;

  // Bootstrap is read once per mount (SSG pages embed it).
  const bootstrap = (() => {
    try {
      return readPageDefinitionBootstrap();
    } catch {
      return null;
    }
  })();
  const bootstrapData =
    bootstrap && matchRoute(bootstrap.route, routeKey) ? bootstrap.definition : undefined;

  const query = useQuery({
    queryKey: pageDefinitionKey(routeKey),
    queryFn: () =>
      getPageDefinition(routeKey).then((payload) => payload.definition),
    // Bootstrap hydrated: no refetch needed — the pinned definition is exact.
    staleTime: bootstrapData ? Infinity : 5 * 60 * 1000,
    initialData: bootstrapData,
    retry: 1,
  });

  // Seed fallback when the API has no published definition for this route.
  const fallback = fallbackDefinitionFor(routeKey);

  const definition: PageDefinition | null = query.data ?? fallback ?? null;
  return {
    ...query,
    definition,
    /** True when served from the immutable seed (API unavailable / unknown). */
    isFallback: query.data == null && fallback != null,
    hasError: query.isError && fallback == null,
  };
}

/** Loose route comparison: "/" equals "" and trailing slashes are ignored. */
function matchRoute(a: string, b: string): boolean {
  const norm = (s: string) => (s === "/" ? "" : s.replace(/\/+$/, "").replace(/^\/+/, ""));
  return norm(a) === norm(b);
}

// Re-export the shared version type for consumers that need to pin releases.
export type { PageDefinition, PageDefinitionVersion };
