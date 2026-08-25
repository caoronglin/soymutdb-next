/**
 * Page-definition loader (Phase 8).
 *
 * Resolves the published PageDefinition for a route from the public API
 * (`GET /page-definitions/{route}`), hydrates from the SSG-embedded bootstrap
 * (`#rl-page-definition`) when the pinned version matches so the first paint
 * needs no refetch. Development/demo builds may use the immutable seed when the
 * API is unavailable; production builds fail closed instead.
 *
 * A release-pinned definition never silently downgrades: when a bootstrap
 * carries a `version`, the loader prefers it over a fresh API fetch.
 */

import { useQuery } from "@tanstack/react-query";
import { getPageDefinition } from "@soymutdb/api-client";
import { isProductionDeploymentMode } from "../lib/deployment";
import {
  normalizePageDefinition,
  type PageDefinitionV2,
  type PageDefinitionVersion,
} from "@soymutdb/shared";
import {
  fallbackDefinitionFor,
} from "./seed";

/** Bootstrap tag id for page definitions (distinct from `rl-bootstrap`). */
const BOOTSTRAP_ID = "rl-page-definition";

/** The embedded bootstrap payload shape written by the SSG pipeline. */
export interface PageDefinitionBootstrap {
  route: string;
  version: number;
  version_id: string | null;
  definition: PageDefinitionV2;
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
    const definition = normalizePageDefinition(raw.definition);
    if (!definition) return null;
    return { ...raw, definition } as unknown as PageDefinitionBootstrap;
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
 *   2. Public API (background).
 *   3. Immutable seed fallback outside strict production mode when the API is unavailable.
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
      getPageDefinition(routeKey).then((payload) => normalizePageDefinition(payload.definition)),
    // Bootstrap hydrated: no refetch needed — the pinned definition is exact.
    staleTime: bootstrapData ? Infinity : 5 * 60 * 1000,
    initialData: bootstrapData,
    retry: 1,
  });

  // Production must fail closed: demo/seed definitions are not release evidence.
  // Standard/dev and demo builds may use the explicit immutable fallback.
  const fallback = resolveFallbackDefinition(routeKey);

  const definition: PageDefinitionV2 | null = query.data ?? fallback;
  return {
    ...query,
    definition,
    /** True when served from the immutable seed (API unavailable / unknown). */
    isFallback: query.data == null && fallback != null,
    hasError: query.isError && fallback == null,
  };
}

/** Resolve the explicit seed only for non-production builds. */
export function resolveFallbackDefinition(route: string): PageDefinitionV2 | null {
  return isProductionDeploymentMode(import.meta.env.VITE_DEPLOYMENT_MODE)
    ? null
    : normalizePageDefinition(fallbackDefinitionFor(route));
}

/** Loose route comparison: "/" equals "" and trailing slashes are ignored. */
function matchRoute(a: string, b: string): boolean {
  const norm = (s: string) => (s === "/" ? "" : s.replace(/\/+$/, "").replace(/^\/+/, ""));
  return norm(a) === norm(b);
}

// Re-export the shared version type for consumers that need to pin releases.
export type { PageDefinitionV2 as PageDefinition, PageDefinitionVersion };
