/**
 * Typed TanStack Vue Query factories for the portal's server state.
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
 */

import { queryOptions } from "@tanstack/vue-query";

import {
  getAssemblies,
  getDownloadFiles,
  getGene,
  getMutantLine,
  getMutantLinePhenotypes,
  getNewsBySlug,
  globalSearch,
  listMutantLines,
  listNews,
  searchVariants,
  type SearchResultType,
} from "@soymutdb/api-client";
import { queryKeys } from "@soymutdb/query-keys";

import type { SiteVariant } from "./deployment";

export const DOWNLOADS_QUERY_KEY = ["downloads"] as const;

export interface DeploymentContext {
  releaseId: string | null;
  siteVariant: SiteVariant;
}

/**
 * Assembly metadata is global reference data: it does not vary by release or
 * site variant, so the key intentionally carries neither (plan §14 scopes the
 * biological reads, not the reference catalogue).
 */
export function assembliesQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.assemblies.all(),
    queryFn: () => getAssemblies(),
    staleTime: 5 * 60_000,
  });
}

export function geneQueryOptions(
  context: DeploymentContext & { geneId: string; assemblyId?: string },
) {
  return queryOptions({
    queryKey: queryKeys.genes.detail(
      context.geneId,
      context.assemblyId,
      context.releaseId,
      context.siteVariant,
    ),
    queryFn: () => getGene(context.geneId, { assembly_id: context.assemblyId }),
    staleTime: 60_000,
  });
}

export function mutantLineQueryOptions(
  context: DeploymentContext & { publicId: string },
) {
  return queryOptions({
    queryKey: queryKeys.mutants.detail(
      context.publicId,
      context.releaseId,
      context.siteVariant,
    ),
    queryFn: () => getMutantLine(context.publicId),
    staleTime: 60_000,
  });
}

export function mutantLinesQueryOptions(
  context: DeploymentContext & { mutagen?: string; limit: number },
) {
  return queryOptions({
    queryKey: queryKeys.mutants.list({
      mutagen: context.mutagen ?? null,
      limit: context.limit,
      releaseId: context.releaseId,
      siteVariant: context.siteVariant,
    }),
    queryFn: () => listMutantLines({ mutagen: context.mutagen, limit: context.limit }),
    staleTime: 60_000,
  });
}

export interface VariantFilters {
  assemblyId: string | null;
  chromosome?: string;
  start?: number;
  end?: number;
  impact?: string;
}

export function variantsQueryOptions(
  context: DeploymentContext & VariantFilters & { page: number; limit: number },
) {
  return queryOptions({
    queryKey: queryKeys.variants.list({
      assemblyId: context.assemblyId,
      releaseId: context.releaseId,
      siteVariant: context.siteVariant,
      page: context.page,
      chromosome: context.chromosome ?? null,
      start: context.start ?? null,
      end: context.end ?? null,
      impact: context.impact ?? null,
    }),
    queryFn: () =>
      searchVariants({
        assembly: context.assemblyId ?? undefined,
        chromosome: context.chromosome || undefined,
        start: context.start,
        end: context.end,
        impact: (context.impact || undefined) as never,
        limit: context.limit,
      }),
    staleTime: 30_000,
  });
}

export function globalSearchQueryOptions(
  context: DeploymentContext & {
    query: string | undefined;
    types: readonly SearchResultType[] | undefined;
    cursor: string | undefined;
    limit: number;
    assemblyId: string | undefined;
    federated: boolean;
    sources: readonly string[] | undefined;
  },
) {
  return queryOptions({
    queryKey: queryKeys.search.global({
      query: context.query,
      types: context.types,
      cursor: context.cursor,
      limit: context.limit,
      assemblyId: context.assemblyId,
      releaseId: context.releaseId,
      siteVariant: context.siteVariant,
      federated: context.federated,
    }),
    queryFn: () =>
      globalSearch({
        q: context.query!,
        types: context.types as SearchResultType[] | undefined,
        cursor: context.cursor,
        limit: context.limit,
        assembly_id: context.assemblyId ? Number(context.assemblyId) : undefined,
        sources: context.federated ? [...(context.sources ?? [])] : undefined,
      }),
    enabled: Boolean(context.query?.trim()),
    staleTime: 60_000,
  });
}

/**
 * Downloads are a content catalogue, not a biological search: the endpoint is
 * not release/assembly scoped, so the key carries only the category filter.
 */
export function downloadsQueryOptions(context: { category?: string }) {
  return queryOptions({
    queryKey: [...DOWNLOADS_QUERY_KEY, context.category ?? null] as const,
    queryFn: () => getDownloadFiles(context.category),
    staleTime: 60_000,
  });
}

/**
 * News is global public content: the key carries only the filters that change
 * the result set (category/page/page size), never release or site variant.
 */
export function newsListQueryOptions(context: {
  category?: string;
  page: number;
  pageSize: number;
}) {
  return queryOptions({
    queryKey: queryKeys.news.list({
      category: context.category ?? null,
      page: context.page,
      pageSize: context.pageSize,
    }),
    queryFn: () => listNews(context.category, context.page, context.pageSize),
    staleTime: 60_000,
  });
}

export function newsDetailQueryOptions(context: { slug: string }) {
  return queryOptions({
    queryKey: queryKeys.news.detail(context.slug),
    queryFn: () => getNewsBySlug(context.slug),
    staleTime: 60_000,
  });
}

/**
 * Phenotype observations for one public mutant line. The key carries the same
 * release/site context as the line detail so a context switch refetches.
 */
export function mutantLinePhenotypesQueryOptions(
  context: DeploymentContext & { publicId: string; enabled?: boolean },
) {
  return queryOptions({
    queryKey: queryKeys.mutants.phenotypes(
      context.publicId,
      context.releaseId,
      context.siteVariant,
    ),
    queryFn: () => getMutantLinePhenotypes(context.publicId),
    enabled: context.enabled ?? true,
    staleTime: 60_000,
  });
}
