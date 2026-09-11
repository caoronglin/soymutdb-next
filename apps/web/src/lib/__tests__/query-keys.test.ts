import { describe, expect, it } from "vitest";
import { queryKeys } from "../query-keys";

describe("queryKeys", () => {
  it("shares one stable assemblies key across routes", () => {
    expect(queryKeys.assemblies.all()).toEqual(["soymutdb", "assemblies"]);
  });

  it("scopes chromosome keys beneath the assemblies prefix", () => {
    expect(queryKeys.assemblies.chromosomes("wm82-v4")).toEqual([
      "soymutdb",
      "assemblies",
      "chromosomes",
      "wm82-v4",
    ]);
    expect(queryKeys.assemblies.chromosomes(undefined)).toEqual([
      "soymutdb",
      "assemblies",
      "chromosomes",
      null,
    ]);
  });

  it("keeps gene details within their domain prefix", () => {
    expect(queryKeys.genes.detail("Glyma.01G000100")).toEqual([
      "soymutdb",
      "genes",
      "detail",
      "Glyma.01G000100",
      null,
    ]);
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
      federated: false,
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
      false,
    ]);
    expect(queryKeys.search.global({ ...base, assemblyId: "5" })).not.toEqual(externalKey);
    expect(queryKeys.search.global({ ...base, releaseId: "2026.10" })).not.toEqual(externalKey);
    expect(queryKeys.search.global({ ...base, siteVariant: "internal" })).not.toEqual(externalKey);
    expect(queryKeys.search.global({ ...base, federated: true })).not.toEqual(externalKey);
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
  });
});
