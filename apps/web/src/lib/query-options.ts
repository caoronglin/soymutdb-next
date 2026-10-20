/**
 * Typed TanStack React Query factories for the portal's assembly server state.
 *
 * The shared `@soymutdb/query-keys` package owns the cache identity; this layer
 * co-locates each key with its query function, stale time, and the deployment
 * context so the two cannot drift apart (plan.md §14/§15, review R1):
 *
 *     packages/query-keys  ->  queryOptions factories  ->  view
 *
 * Every factory takes the deployment context explicitly. A view cannot forget
 * the release/site boundary or a result-affecting filter because the key is
 * derived from the same object the request is built from.
 *
 * This module used to export factories for genes, variants, regions,
 * analytics, downloads, news and mutant lines. Those routes now call
 * `useQuery` directly with `@soymutdb/query-keys`, so only the two assembly
 * factories below still have importers; the rest were removed as dead code
 * (2026-10-18, knip `exports` category).
 */

import { queryOptions } from "@tanstack/react-query";

import { getAssemblies, getAssemblyChromosomes, getReleaseId } from "@soymutdb/api-client";
import { queryKeys } from "@soymutdb/query-keys";

import type { SiteVariant } from "./deployment";

export interface DeploymentContext {
  releaseId: string | null;
  siteVariant: SiteVariant;
}

// The transport owns release pinning. A retained query must not populate an
// old cache key after its release header changes.
function assertAssemblyRelease(context: DeploymentContext) {
  if (context.releaseId !== getReleaseId()) {
    throw new Error("Assembly query release differs from transport release");
  }
}

/** null keeps active-release semantics; all() is invalidation only. */
export function assembliesQueryOptions(context: DeploymentContext) {
  return queryOptions({
    queryKey: queryKeys.assemblies.list(context),
    queryFn: () => {
      assertAssemblyRelease(context);
      return getAssemblies();
    },
    staleTime: 5 * 60_000,
  });
}

export function assemblyChromosomesQueryOptions(
  context: DeploymentContext & { assemblyId: string | number | undefined },
) {
  return queryOptions({
    queryKey: queryKeys.assemblies.chromosomes(context.assemblyId, context),
    queryFn: () => {
      assertAssemblyRelease(context);
      if (context.assemblyId == null) throw new Error("Assembly is unresolved");
      return getAssemblyChromosomes(context.assemblyId);
    },
    enabled: context.assemblyId != null,
    staleTime: 5 * 60_000,
  });
}
