/**
 * Shared TanStack Query keys for public portal data.
 *
 * Framework-neutral seam (Phase C): these are plain, serialisable key arrays
 * consumed identically by TanStack React Query today and TanStack Vue Query
 * after the migration. Keep keys centralised so equivalent reads share cache
 * entries and future invalidation can use stable prefixes instead of
 * handwritten arrays.
 *
 * Every biological read is scoped by the context that changes its result set —
 * query, assembly, release, site variant, filters, pagination — so caches never
 * cross site-variant / release / assembly boundaries (DB-CORE-6 / CTX-01..03).
 */
export const queryKeys = {
  all: ["soymutdb"] as const,
  assemblies: {
    all: () => [...queryKeys.all, "assemblies"] as const,
    chromosomes: (assemblyId: string | number | undefined) =>
      [...queryKeys.assemblies.all(), "chromosomes", assemblyId ?? null] as const,
  },
  genes: {
    all: () => [...queryKeys.all, "genes"] as const,
    detail: (geneId: string, assemblyId?: string) =>
      [...queryKeys.genes.all(), "detail", geneId, assemblyId ?? null] as const,
    expression: (geneId: string, assemblyId?: string) =>
      [...queryKeys.genes.all(), "expression", geneId, assemblyId ?? null] as const,
    homologs: (geneId: string, assemblyId?: string) =>
      [...queryKeys.genes.all(), "homologs", geneId, assemblyId ?? null] as const,
    search: (context: {
      q: string | undefined;
      assemblyId: string | undefined;
      page: number;
      releaseId: string | null;
      siteVariant: "external" | "internal";
    }) =>
      [
        ...queryKeys.genes.all(),
        "search",
        context.q ?? null,
        context.assemblyId ?? null,
        context.page,
        context.releaseId,
        context.siteVariant,
      ] as const,
  },
  search: {
    all: () => [...queryKeys.all, "search"] as const,
    global: (context: {
      query: string | undefined;
      types: readonly string[] | undefined;
      cursor: string | undefined;
      limit: number;
      assemblyId: string | undefined;
      releaseId: string | null;
      siteVariant: "external" | "internal";
      federated: boolean;
    }) => [
      ...queryKeys.search.all(),
      "global",
      context.query ?? null,
      context.types ?? null,
      context.cursor ?? null,
      context.limit,
      context.assemblyId ?? null,
      context.releaseId,
      context.siteVariant,
      context.federated,
    ] as const,
  },
} as const;

export type QueryKeys = typeof queryKeys;
