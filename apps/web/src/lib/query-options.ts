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

import { infiniteQueryOptions, queryOptions } from "@tanstack/vue-query";

import {
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
 * Region search: assembly name + chromosome + 1-based inclusive interval. The
 * coordinates are only meaningful inside the assembly the name resolves to.
 */
export function regionVariantsQueryOptions(
  context: DeploymentContext & {
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
        assemblyName: context.assemblyName,
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
      context.assemblyName && context.chromosome && context.start && context.end,
    ),
    staleTime: 30_000,
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
    initialPageParam: undefined as number | undefined,
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
