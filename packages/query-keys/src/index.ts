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
    // Bare prefix: invalidation (`queryKeys.assemblies.all()`) must stay a
    // prefix of every context-scoped child key below.
    all: () => [...queryKeys.all, "assemblies"] as const,
    // The assembly catalogue itself is release- and site-scoped: switching
    // either must not reuse the previous deployment's assembly list.
    list: (context?: { releaseId?: string | null; siteVariant?: "external" | "internal" }) =>
      [
        ...queryKeys.assemblies.all(),
        "list",
        context?.releaseId ?? null,
        context?.siteVariant ?? null,
      ] as const,
    chromosomes: (
      assemblyId: string | number | undefined,
      context?: { releaseId?: string | null; siteVariant?: "external" | "internal" },
    ) =>
      [
        ...queryKeys.assemblies.all(),
        "chromosomes",
        assemblyId ?? null,
        context?.releaseId ?? null,
        context?.siteVariant ?? null,
      ] as const,
  },
  news: {
    all: () => [...queryKeys.all, "news"] as const,
    // News is global public content (no release/assembly scoping); the key
    // carries the filters that change the result set.
    list: (context: { category: string | null; page: number; pageSize: number }) =>
      [
        ...queryKeys.news.all(),
        "list",
        context.category ?? null,
        context.page,
        context.pageSize,
      ] as const,
    detail: (slug: string) => [...queryKeys.news.all(), "detail", slug] as const,
  },
  genes: {
    all: () => [...queryKeys.all, "genes"] as const,
    // Gene details are release-scoped by the API's ReleaseContext and the
    // client release header, and the external/internal site is a cache
    // boundary (DB-CORE-6). Both belong in the key or a release/site switch
    // can reuse the previous release's cached detail.
    detail: (
      geneId: string,
      assemblyId: string | undefined,
      releaseId: string | null,
      siteVariant: "external" | "internal",
    ) =>
      [
        ...queryKeys.genes.all(),
        "detail",
        geneId,
        assemblyId ?? null,
        releaseId,
        siteVariant,
      ] as const,
    expression: (context: {
      geneId: string;
      assemblyId?: string;
      releaseId: string | null;
      siteVariant: "external" | "internal";
    }) =>
      [
        ...queryKeys.genes.all(),
        "expression",
        context.geneId,
        context.assemblyId ?? null,
        context.releaseId,
        context.siteVariant,
      ] as const,
    homologs: (context: {
      geneId: string;
      assemblyId?: string;
      releaseId: string | null;
      siteVariant: "external" | "internal";
    }) =>
      [
        ...queryKeys.genes.all(),
        "homologs",
        context.geneId,
        context.assemblyId ?? null,
        context.releaseId,
        context.siteVariant,
      ] as const,
    search: (context: {
      q: string | undefined;
      assemblyId: string | undefined;
      chromosome?: string | undefined;
      biotype?: string | undefined;
      page: number;
      pageSize?: number;
      sortBy?: string | undefined;
      sortDir?: string | undefined;
      releaseId: string | null;
      siteVariant: "external" | "internal";
    }) =>
      [
        ...queryKeys.genes.all(),
        "search",
        context.q ?? null,
        context.assemblyId ?? null,
        context.chromosome ?? null,
        context.biotype ?? null,
        context.page,
        context.pageSize ?? null,
        context.sortBy ?? null,
        context.sortDir ?? null,
        context.releaseId,
        context.siteVariant,
      ] as const,
  },
  search: {
    all: () => [...queryKeys.all, "search"] as const,
    // `federated` was dropped from the key when external-source search was
    // retired: the response can no longer vary by that flag, so keeping it in
    // the key would only fragment the cache.
    global: (context: {
      query: string | undefined;
      types: readonly string[] | undefined;
      cursor: string | undefined;
      limit: number;
      assemblyId: string | undefined;
      releaseId: string | null;
      siteVariant: "external" | "internal";
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
    ] as const,
  },
  mutants: {
    all: () => [...queryKeys.all, "mutants"] as const,
    // Public mutant lines keyed by filter + site/release so caches never cross
    // site-variant/release boundaries (DB-CORE-6). Keyed by public_id only.
    list: (context: { mutagen: string | null; limit: number; releaseId: string | null; siteVariant: "external" | "internal" }) =>
      [
        ...queryKeys.mutants.all(),
        "list",
        context.mutagen ?? null,
        context.limit,
        context.releaseId,
        context.siteVariant,
      ] as const,
    detail: (publicId: string, releaseId: string | null, siteVariant: "external" | "internal") =>
      [...queryKeys.mutants.all(), "detail", publicId, releaseId, siteVariant] as const,
    // Phenotype observations are read under the same release/site budget as the
    // line itself; a release switch must not reuse the previous release's rows.
    phenotypes: (
      publicId: string,
      releaseId: string | null,
      siteVariant: "external" | "internal",
    ) =>
      [
        ...queryKeys.mutants.all(),
        "phenotypes",
        publicId,
        releaseId,
        siteVariant,
      ] as const,
  },
  variants: {
    all: () => [...queryKeys.all, "variants"] as const,
    // Every variable the variant search sends belongs in the key: assembly,
    // site, release, pagination AND the region/impact filters. Omitting the
    // filters let a changed chromosome/start/end/impact reuse the previous
    // filter's cached page. The cursor is part of the key too: a cursor URL
    // that happens to share a page index with the first page otherwise reads
    // the first page's cached rows.
    list: (context: {
      assemblyId: string | null;
      releaseId: string | null;
      siteVariant: "external" | "internal";
      page: number;
      cursor?: string | null;
      chromosome?: string | null;
      start?: number | null;
      end?: number | null;
      impact?: string | null;
      variantType?: string | null;
      /** Public mutant-line identifier; the internal key never keys a cache. */
      mutantLinePublicId?: string | null;
    }) =>
      [
        ...queryKeys.variants.all(),
        "list",
        context.assemblyId ?? null,
        context.releaseId,
        context.siteVariant,
        context.page,
        context.cursor ?? null,
        context.chromosome ?? null,
        context.start ?? null,
        context.end ?? null,
        context.impact ?? null,
        context.variantType ?? null,
        context.mutantLinePublicId ?? null,
      ] as const,
  },
} as const;

export type QueryKeys = typeof queryKeys;
