/**
 * Shared TanStack Query keys for public Web data.
 *
 * Keep keys centralized so equivalent reads share cache entries and future
 * invalidation can use stable prefixes instead of handwritten arrays.
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
