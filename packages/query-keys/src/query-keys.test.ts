import { describe, expect, it } from "vitest";
import { queryKeys } from "./index";

describe("queryKeys", () => {
  it("keeps the bare assemblies prefix stable for invalidation", () => {
    expect(queryKeys.assemblies.all()).toEqual(["soymutdb", "assemblies"]);
    // Context-scoped children stay beneath that prefix.
    expect(queryKeys.assemblies.list({ releaseId: "2026.09", siteVariant: "external" }).slice(0, 2)).toEqual([
      "soymutdb",
      "assemblies",
    ]);
  });

  it("scopes the assembly catalogue by release and site variant", () => {
    const base = { releaseId: "2026.09", siteVariant: "external" as const };
    const key = queryKeys.assemblies.list(base);
    expect(queryKeys.assemblies.list({ ...base, releaseId: "2026.10" })).not.toEqual(key);
    expect(queryKeys.assemblies.list({ ...base, siteVariant: "internal" })).not.toEqual(key);
  });

  it("scopes chromosome keys beneath the assemblies prefix and by context", () => {
    const base = { releaseId: "2026.09", siteVariant: "external" as const };
    expect(queryKeys.assemblies.chromosomes("wm82-v4", base)).toEqual([
      "soymutdb",
      "assemblies",
      "chromosomes",
      "wm82-v4",
      "2026.09",
      "external",
    ]);
    expect(queryKeys.assemblies.chromosomes(undefined, base)).toEqual([
      "soymutdb",
      "assemblies",
      "chromosomes",
      null,
      "2026.09",
      "external",
    ]);
    // A release or site switch must not reuse the previous chromosomes.
    expect(queryKeys.assemblies.chromosomes("wm82-v4", { ...base, releaseId: "2026.10" })).not.toEqual(
      queryKeys.assemblies.chromosomes("wm82-v4", base),
    );
    expect(queryKeys.assemblies.chromosomes("wm82-v4", { ...base, siteVariant: "internal" })).not.toEqual(
      queryKeys.assemblies.chromosomes("wm82-v4", base),
    );
  });

  it("keeps gene details within their domain prefix", () => {
    expect(queryKeys.genes.detail("Glyma.01G000100", undefined, null, "external")).toEqual([
      "soymutdb",
      "genes",
      "detail",
      "Glyma.01G000100",
      null,
      null,
      "external",
    ]);
  });

  it("scopes gene detail caches by assembly, release and site variant", () => {
    const base = { geneId: "Glyma.01G000100", assemblyId: "5", releaseId: "2026.09", siteVariant: "external" as const };
    const detail = queryKeys.genes.detail(base.geneId, base.assemblyId, base.releaseId, base.siteVariant);
    expect(detail).toContain("2026.09");
    expect(detail).toContain("external");
    expect(queryKeys.genes.detail(base.geneId, "4", base.releaseId, base.siteVariant)).not.toEqual(detail);
    expect(queryKeys.genes.detail(base.geneId, base.assemblyId, "2026.10", base.siteVariant)).not.toEqual(detail);
    expect(queryKeys.genes.detail(base.geneId, base.assemblyId, base.releaseId, "internal")).not.toEqual(detail);
  });

  it("scopes gene expression and homolog caches by assembly, release and site variant", () => {
    const base = {
      geneId: "Glyma.01G000100",
      assemblyId: "5",
      releaseId: "2026.09",
      siteVariant: "external" as const,
    };
    const expression = queryKeys.genes.expression(base);
    const homologs = queryKeys.genes.homologs(base);

    for (const makeKey of [queryKeys.genes.expression, queryKeys.genes.homologs]) {
      const key = makeKey(base);
      expect(makeKey({ ...base, assemblyId: "4" })).not.toEqual(key);
      expect(makeKey({ ...base, releaseId: "2026.10" })).not.toEqual(key);
      expect(makeKey({ ...base, siteVariant: "internal" })).not.toEqual(key);
    }

    expect(expression).not.toEqual(homologs);
  });

  it("separates global search caches by biological and deployment context", () => {
    const base = {
      query: "Glyma.01G000100",
      types: ["gene"],
      cursor: undefined,
      limit: 20,
      assemblyId: "4",
      releaseId: "2026.09",
      siteVariant: "external" as const,
    };

    const externalKey = queryKeys.search.global(base);
    expect(externalKey).toEqual([
      "soymutdb",
      "search",
      "global",
      "Glyma.01G000100",
      ["gene"],
      null,
      20,
      "4",
      "2026.09",
      "external",
    ]);
    expect(queryKeys.search.global({ ...base, assemblyId: "5" })).not.toEqual(externalKey);
    expect(queryKeys.search.global({ ...base, releaseId: "2026.10" })).not.toEqual(externalKey);
    expect(queryKeys.search.global({ ...base, siteVariant: "internal" })).not.toEqual(externalKey);
  });

  it("scopes gene search caches by query, assembly, page, release and site", () => {
    const base = {
      q: "Glyma.01G000100",
      assemblyId: "4",
      page: 1,
      releaseId: "2026.09",
      siteVariant: "external" as const,
    };

    const geneKey = queryKeys.genes.search(base);
    expect(geneKey[2]).toBe("search");
    expect(queryKeys.genes.search({ ...base, assemblyId: "5" })).not.toEqual(geneKey);
    expect(queryKeys.genes.search({ ...base, q: "Glyma.01G000200" })).not.toEqual(geneKey);
    expect(queryKeys.genes.search({ ...base, releaseId: "2026.10" })).not.toEqual(geneKey);
    expect(queryKeys.genes.search({ ...base, siteVariant: "internal" })).not.toEqual(geneKey);
    // Pagination within the same context shares one cache entry.
    expect(queryKeys.genes.search({ ...base, page: 2 })).not.toEqual(geneKey);
    // Every server-affecting filter/sort must key the cache: the route sends
    // chromosome, biotype, page size and sort, so omitting them showed prior
    // rows after a filter change.
    expect(queryKeys.genes.search({ ...base, chromosome: "Chr02" })).not.toEqual(geneKey);
    expect(queryKeys.genes.search({ ...base, biotype: "protein_coding" })).not.toEqual(geneKey);
    expect(queryKeys.genes.search({ ...base, pageSize: 50 })).not.toEqual(geneKey);
    expect(queryKeys.genes.search({ ...base, sortBy: "variant_count" })).not.toEqual(geneKey);
    expect(queryKeys.genes.search({ ...base, sortDir: "desc" })).not.toEqual(geneKey);
  });

  it("scopes mutant caches by mutagen/release/site and keys detail by public id", () => {
    const base = { mutagen: "EMS", limit: 20, releaseId: "2026.09", siteVariant: "external" as const };
    const listKey = queryKeys.mutants.list(base);
    expect(queryKeys.mutants.list({ ...base, mutagen: "gamma" })).not.toEqual(listKey);
    expect(queryKeys.mutants.list({ ...base, releaseId: "2026.10" })).not.toEqual(listKey);
    expect(queryKeys.mutants.list({ ...base, siteVariant: "internal" })).not.toEqual(listKey);
    // Detail is keyed by the public identifier only (never an internal id).
    const detail = queryKeys.mutants.detail("SM7QF3Z", "2026.09", "external");
    expect(detail).toContain("SM7QF3Z");
    expect(detail).not.toContain("internal_id");
  });

  it("scopes variant caches by assembly/release/site and every result-affecting filter", () => {
    const base = {
      assemblyId: "5",
      releaseId: "2026.09",
      siteVariant: "external" as const,
      page: 1,
      chromosome: "Chr01",
      start: 1000,
      end: 2000,
      impact: "HIGH",
    };
    const key = queryKeys.variants.list(base);
    expect(queryKeys.variants.list({ ...base, assemblyId: "4" })).not.toEqual(key);
    expect(queryKeys.variants.list({ ...base, releaseId: "2026.10" })).not.toEqual(key);
    expect(queryKeys.variants.list({ ...base, siteVariant: "internal" })).not.toEqual(key);
    expect(queryKeys.variants.list({ ...base, page: 2 })).not.toEqual(key);
    // The review found the filters missing from the key: changing any of them
    // must produce a different cache entry, not reuse the previous page.
    expect(queryKeys.variants.list({ ...base, chromosome: "Chr02" })).not.toEqual(key);
    expect(queryKeys.variants.list({ ...base, start: 2000 })).not.toEqual(key);
    expect(queryKeys.variants.list({ ...base, end: 3000 })).not.toEqual(key);
    expect(queryKeys.variants.list({ ...base, impact: "LOW" })).not.toEqual(key);
    expect(queryKeys.variants.list({ ...base, variantType: "SNP" })).not.toEqual(key);
    expect(queryKeys.variants.list({ ...base, mutantLinePublicId: "SM7QF3Z" })).not.toEqual(key);
    // P1-04: the cursor is sent to the API, so it must key the cache too. A
    // cursor URL that happens to share a page index with page one otherwise
    // reads page one's cached rows.
    expect(queryKeys.variants.list({ ...base, cursor: "c2" })).not.toEqual(
      queryKeys.variants.list({ ...base, cursor: "c1" }),
    );
    expect(queryKeys.variants.list({ ...base, cursor: "c1" })).not.toEqual(key);
  });

  it("scopes news caches by category, page and page size", () => {    const base = { category: "update", page: 1, pageSize: 10 };
    const listKey = queryKeys.news.list(base);
    expect(queryKeys.news.list({ ...base, category: "news" })).not.toEqual(listKey);
    expect(queryKeys.news.list({ ...base, page: 2 })).not.toEqual(listKey);
    expect(queryKeys.news.list({ ...base, pageSize: 20 })).not.toEqual(listKey);
    // An absent category (the "all" tab) is part of the identity.
    expect(queryKeys.news.list({ ...base, category: null })).not.toEqual(listKey);

    // Phenotype observations share the mutants namespace and its release/site
    // context: a release or site switch must not reuse the previous rows.
    const phenotypeKey = queryKeys.mutants.phenotypes("SM7QF3Z", "2026.09", "external");
    expect(queryKeys.mutants.phenotypes("SM7QF3Z", "2026.10", "external")).not.toEqual(
      phenotypeKey,
    );
    expect(queryKeys.mutants.phenotypes("SM7QF3Z", "2026.09", "internal")).not.toEqual(
      phenotypeKey,
    );

    const detail = queryKeys.news.detail("release-2026-09");
    expect(detail).toContain("release-2026-09");
    expect(detail[2]).toBe("detail");
  });

  it("scopes comparative reads by family context and keeps artifacts off the family key", () => {
    const base = { assemblyId: "2", level: "gene_family", page: 1, pageSize: 20, releaseId: "2026.09", siteVariant: "external" as const };
    const key = queryKeys.comparative.families(base);
    // A different assembly answers with a different member set.
    expect(queryKeys.comparative.families({ ...base, assemblyId: "3" })).not.toEqual(key);
    expect(queryKeys.comparative.families({ ...base, level: "gene_subfamily" })).not.toEqual(key);
    expect(queryKeys.comparative.families({ ...base, page: 2 })).not.toEqual(key);
    expect(queryKeys.comparative.families({ ...base, releaseId: "2026.10" })).not.toEqual(key);
    expect(queryKeys.comparative.families({ ...base, siteVariant: "internal" })).not.toEqual(key);

    const detail = queryKeys.comparative.family({
      familyId: 12,
      assemblyId: "2",
      releaseId: "2026.09",
      siteVariant: "external",
    });
    expect(detail.slice(0, 2)).toEqual(["soymutdb", "comparative"]);
    expect(detail).toContain(12);

    // A finished alignment belongs to a frozen input set, not to the family's
    // current membership: the artifact key must not collide with the family key.
    const artifact = queryKeys.comparative.artifact("job-1", "2026.09", "external");
    expect(artifact).not.toEqual(detail);
    expect(queryKeys.comparative.artifact("job-2", "2026.09", "external")).not.toEqual(artifact);
  });

  it("scopes the export cache by export id and session", () => {
    // The export record is owner-scoped: the id identifies the request and
    // the session identifies the account that may read it.
    const key = queryKeys.variants.export("export-1", 7);
    expect(queryKeys.variants.export("export-2", 7)).not.toEqual(key);
    expect(queryKeys.variants.export("export-1", 8)).not.toEqual(key);
    // It must not collide with the variant list cache.
    expect(queryKeys.variants.export("export-1", 7)).not.toEqual(
      queryKeys.variants.list({
        assemblyId: "1",
        releaseId: null,
        siteVariant: "external",
        page: 1,
      }),
    );
  });
});
