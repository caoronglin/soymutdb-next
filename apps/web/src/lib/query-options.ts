/**
 * Typed TanStack React Query factories for the portal's server state.
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

import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import {
  fetchChromosomeDensity,
  fetchDiscoveryTrend,
  fetchImpactSummary,
  fetchMutagenStatistics,
  fetchVariantTypeSummary,
  getAssemblies,
  getAssemblyChromosomes,
  getTableView,
  getDownloadFiles,
  getGene,
  getGeneExpression,
  getGeneHomologs,
  getMutantLine,
  getMutantLinePhenotypes,
  getNewsBySlug,
  getFeaturedNews,
  globalSearch,
  listMutantLines,
  listNews,
  searchGenes,
  searchRegionVariants,
  searchVariants,
  type SearchResultType,
} from "@soymutdb/api-client";
import { queryKeys } from "@soymutdb/query-keys";

import { resolveSiteVariant, type SiteVariant } from "./deployment";

export const DOWNLOADS_QUERY_KEY = ["downloads"] as const;
export const GENE_DATA_PAGE_SIZE = 50;
export const GENE_LIST_PAGE_SIZE = 20;
export const GENE_SEARCH_PAGE_SIZE = 20;
export const REGION_SEARCH_MAX_RESULTS = 1000;

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

export interface GeneListFilters {
  q?: string;
  chromosome?: string;
  biotype?: string;
  assemblyId?: string | null;
  page: number;
  pageSize: number;
  sortBy: string;
  sortDir: "asc" | "desc";
}

/**
 * Gene index (server-side paginated list). Every result-affecting filter is in
 * the key, so a filter change can never reuse another filter's cached rows.
 */
export function geneListQueryOptions(context: DeploymentContext & GeneListFilters) {
  return queryOptions({
    queryKey: [
      ...queryKeys.genes.search({
        q: context.q ?? undefined,
        assemblyId: context.assemblyId ?? undefined,
        page: context.page,
        releaseId: context.releaseId,
        siteVariant: context.siteVariant,
      }),
      context.chromosome || null,
      context.biotype || null,
      context.pageSize,
      context.sortBy,
      context.sortDir,
    ],
    queryFn: () =>
      searchGenes({
        q: context.q || undefined,
        chromosome: context.chromosome || undefined,
        biotype: context.biotype || undefined,
        assembly_id: context.assemblyId || undefined,
        page: context.page,
        page_size: context.pageSize,
        sort_by: context.sortBy,
        sort_dir: context.sortDir,
      } as Parameters<typeof searchGenes>[0]),
    staleTime: 60_000,
  });
}

/**
 * Gene ID search: one gene list inside one assembly. The assembly is part of
 * the identity because the same accession resolves differently per assembly
 * (DB-CORE-3/4).
 */
export function geneSearchQueryOptions(
  context: DeploymentContext & { q: string | null; assemblyId: string | null; page: number },
) {
  return queryOptions({
    queryKey: [
      "gene-search",
      "released",
      queryKeys.genes.search({
        q: context.q ?? undefined,
        assemblyId: context.assemblyId ?? undefined,
        page: context.page,
        releaseId: context.releaseId,
        siteVariant: context.siteVariant,
      }),
    ],
    queryFn: () =>
      searchGenes({
        q: context.q || undefined,
        assembly_id: context.assemblyId || undefined,
        page: context.page,
        page_size: GENE_SEARCH_PAGE_SIZE,
      } as Parameters<typeof searchGenes>[0]),
    enabled: Boolean(context.q && context.assemblyId),
    staleTime: 60_000,
  });
}

/**
 * Region search: stable assembly id + chromosome + 1-based inclusive interval.
 *
 * Coordinates are only meaningful inside one assembly namespace (DB-CORE-4), so
 * the cache key and the UI state carry the assembly *id*. The label-based
 * backend query is resolved at the request boundary from the id's catalogue
 * entry; a missing label means the caller resolved nothing and the query stays
 * disabled rather than guessing a namespace.
 */
export function regionVariantsQueryOptions(
  context: DeploymentContext & {
    assemblyId: string | null;
    assemblyName: string | null;
    chromosome: string | null;
    start: number | null;
    end: number | null;
    maxResults: number;
  },
) {
  return queryOptions({
    queryKey: [
      "search-region",
      "released",
      {
        assemblyId: context.assemblyId,
        chromosome: context.chromosome,
        start: context.start,
        end: context.end,
        releaseId: context.releaseId,
        siteVariant: context.siteVariant,
      },
    ],
    queryFn: () =>
      searchRegionVariants({
        assembly: context.assemblyName ?? "",
        chromosome: context.chromosome ?? "",
        start: context.start ?? 1,
        end: context.end ?? 1,
        max_results: context.maxResults,
      }),
    enabled: Boolean(
      context.assemblyId && context.assemblyName && context.chromosome && context.start && context.end,
    ),
    staleTime: 30_000,
  });
}

/**
 * Analytics summaries. These are aggregate reads over the whole release, not a
 * filtered result set, so the key carries the release/site context (a context
 * switch must not reuse another release's numbers) and nothing else.
 */
export function chromosomeDensityQueryOptions(context: DeploymentContext) {
  return queryOptions({
    queryKey: ["analytics", "chromosome-density", context.releaseId, context.siteVariant],
    queryFn: () => fetchChromosomeDensity(),
    staleTime: 5 * 60_000,
  });
}

export function variantTypeSummaryQueryOptions(context: DeploymentContext) {
  return queryOptions({
    queryKey: ["analytics", "variant-types", context.releaseId, context.siteVariant],
    queryFn: () => fetchVariantTypeSummary(),
    staleTime: 5 * 60_000,
  });
}

export function impactSummaryQueryOptions(context: DeploymentContext) {
  return queryOptions({
    queryKey: ["analytics", "impact", context.releaseId, context.siteVariant],
    queryFn: () => fetchImpactSummary(),
    staleTime: 5 * 60_000,
  });
}

export function mutagenStatisticsQueryOptions(context: DeploymentContext) {
  return queryOptions({
    queryKey: ["analytics", "mutagens", context.releaseId, context.siteVariant],
    queryFn: () => fetchMutagenStatistics(),
    staleTime: 5 * 60_000,
  });
}

export function discoveryTrendQueryOptions(context: DeploymentContext & { days: number }) {
  return queryOptions({
    queryKey: ["analytics", "discovery-trend", context.days, context.releaseId, context.siteVariant],
    queryFn: () => fetchDiscoveryTrend(context.days),
    staleTime: 5 * 60_000,
  });
}

/**
 * Portal table layouts are configuration, not server state that changes with a
 * filter, but they *are* scoped by release/site variant: the key carries both so
 * a context switch re-resolves the layout instead of reusing the previous
 * deployment's columns.
 */
export function tableViewQueryOptions(
  kind: "mutation_sites" | "variants" | "genes" | "mutant_lines",
  context: { species?: string } = {},
) {
  return queryOptions({
    queryKey: [
      "table-views",
      kind,
      context.species ?? "Glycine max",
      resolveSiteVariant(import.meta.env.VITE_SITE_VARIANT),
    ],
    queryFn: () => getTableView(kind, { species: context.species }),
    staleTime: 5 * 60_000,
  });
}

/** Chromosome metadata is reference data scoped to one assembly. */
export function assemblyChromosomesQueryOptions(context: { assemblyId: string | null }) {
  return queryOptions({
    queryKey: ["assemblies", context.assemblyId, "chromosomes"],
    queryFn: () => getAssemblyChromosomes(context.assemblyId!),
    enabled: Boolean(context.assemblyId),
    staleTime: 30 * 60_000,
  });
}

export function geneExpressionQueryOptions(
  context: DeploymentContext & { geneId: string; assemblyId?: string; enabled?: boolean },
) {
  return infiniteQueryOptions({
    queryKey: queryKeys.genes.expression({
      geneId: context.geneId,
      assemblyId: context.assemblyId,
      releaseId: context.releaseId,
      siteVariant: context.siteVariant,
    }),
    queryFn: ({ pageParam }) =>
      getGeneExpression(context.geneId, {
        assembly_id: context.assemblyId,
        cursor: pageParam,
        limit: GENE_DATA_PAGE_SIZE,
      }),
    // The expression cursor is an opaque release/filter-bound token, so the
    // page parameter is a string (it used to be a raw ExpressionData.id).
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? (lastPage.next_cursor ?? undefined) : undefined,
    enabled: context.enabled ?? true,
    staleTime: 60_000,
  });
}

export function geneHomologsQueryOptions(
  context: DeploymentContext & { geneId: string; assemblyId?: string; enabled?: boolean },
) {
  return infiniteQueryOptions({
    queryKey: queryKeys.genes.homologs({
      geneId: context.geneId,
      assemblyId: context.assemblyId,
      releaseId: context.releaseId,
      siteVariant: context.siteVariant,
    }),
    queryFn: ({ pageParam }) =>
      getGeneHomologs(context.geneId, {
        assembly_id: context.assemblyId,
        cursor: pageParam,
        limit: GENE_DATA_PAGE_SIZE,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? (lastPage.next_cursor ?? undefined) : undefined,
    enabled: context.enabled ?? true,
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
  variantType?: string;
  /** Public mutant-line identifier (never the internal key). */
  mutantLinePublicId?: string;
}
export function variantsQueryOptions(
  context: DeploymentContext & VariantFilters & { page: number; limit: number; cursor?: string; assemblyName?: string | null },
) {
  return queryOptions({
    queryKey: queryKeys.variants.list({
      assemblyId: context.assemblyId,
      releaseId: context.releaseId,
      siteVariant: context.siteVariant,
      page: context.page,
      cursor: context.cursor ?? null,
      chromosome: context.chromosome ?? null,
      start: context.start ?? null,
      end: context.end ?? null,
      impact: context.impact ?? null,
      variantType: context.variantType ?? null,
      mutantLinePublicId: context.mutantLinePublicId ?? null,
    }),
    queryFn: () =>
      searchVariants({
        // The list endpoint filters by assembly label; the stable id stays in
        // the cache key, the label is resolved at this boundary.
        assembly: context.assemblyName || undefined,
        chromosome: context.chromosome || undefined,
        start: context.start,
        end: context.end,
        variant_type: (context.variantType || undefined) as never,
        mutant_line_public_id: context.mutantLinePublicId || undefined,
        impact: (context.impact || undefined) as never,
        cursor: context.cursor,
        limit: context.limit,
      }),
    enabled: !context.assemblyId || Boolean(context.assemblyName),
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
    }),
    queryFn: () =>
      globalSearch({
        q: context.query!,
        types: context.types as SearchResultType[] | undefined,
        cursor: context.cursor,
        limit: context.limit,
        assembly_id: context.assemblyId ? Number(context.assemblyId) : undefined,
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

/** Homepage editorial content; queried separately so failures never look like an empty list. */
export function featuredNewsQueryOptions() {
  return queryOptions({
    queryKey: ["news", "featured"],
    queryFn: async () => {
      const data = await getFeaturedNews();
      // A 200 with the wrong envelope is a contract violation, not an empty
      // homepage: reject it so the section renders its error state instead of
      // silently showing "no news" or crashing a render on `featured.slice`.
      if (!Array.isArray(data?.featured)) {
        throw new Error("Malformed featured-news response");
      }
      return data;
    },
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
