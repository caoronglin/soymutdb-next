/**
 * Runtime cache-isolation evidence for the assembly catalogue.
 *
 * The API caches `/genes/assemblies` per release
 * (`apps/api/app/api/v1/genes.py`: key `genes:assemblies:release:{release_id}`),
 * so the portal must key its own cache the same way. This file proves that with
 * a real QueryClient rather than by reading the key builder: two releases and
 * two site variants each get their own entry, and the transport refuses a
 * context that disagrees with the pinned release.
 */
import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({
  releaseId: "release-a" as string | null,
  assemblies: [] as Array<{ id: number; name: string }>,
  chromosomes: [] as Array<{ name: string }>,
  assemblyCalls: [] as Array<unknown>,
  chromosomeCalls: [] as unknown[],
}));

vi.mock("@soymutdb/api-client", () => ({
  getReleaseId: () => transport.releaseId,
  getAssemblies: async () => {
    transport.assemblyCalls.push(transport.releaseId);
    return transport.assemblies;
  },
  getAssemblyChromosomes: async (assemblyId: string | number) => {
    transport.chromosomeCalls.push(assemblyId);
    return transport.chromosomes;
  },
}));

import { assembliesQueryOptions, assemblyChromosomesQueryOptions } from "./query-options";

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
}

const KEY = (releaseId: string | null, siteVariant: "external" | "internal") =>
  assembliesQueryOptions({ releaseId, siteVariant }).queryKey;

beforeEach(() => {
  transport.releaseId = "release-a";
  transport.assemblies = [{ id: 5, name: "v5" }];
  transport.chromosomes = [{ name: "chr01" }];
  transport.assemblyCalls = [];
  transport.chromosomeCalls = [];
});

describe("assembly catalogue cache identity", () => {
  it("gives each release its own entry and refetches instead of reusing the other one", async () => {
    const qc = client();
    transport.assemblies = [{ id: 5, name: "v5" }];
    await qc.fetchQuery(assembliesQueryOptions({ releaseId: "release-a", siteVariant: "external" }));

    transport.releaseId = "release-b";
    transport.assemblies = [{ id: 4, name: "v4" }];
    const other = await qc.fetchQuery(
      assembliesQueryOptions({ releaseId: "release-b", siteVariant: "external" }),
    );

    expect(other).toEqual([{ id: 4, name: "v4" }]);
    expect(transport.assemblyCalls).toEqual(["release-a", "release-b"]);

    // Going back must still read release A's cached entry, not release B's.
    const backToA = await qc.fetchQuery(
      assembliesQueryOptions({ releaseId: "release-a", siteVariant: "external" }),
    );
    expect(backToA).toEqual([{ id: 5, name: "v5" }]);
    expect(transport.assemblyCalls).toEqual(["release-a", "release-b"]);
  });

  it("separates the two site variants even within one release", async () => {
    const qc = client();
    await qc.fetchQuery(assembliesQueryOptions({ releaseId: "release-a", siteVariant: "external" }));
    await qc.fetchQuery(assembliesQueryOptions({ releaseId: "release-a", siteVariant: "internal" }));
    expect(transport.assemblyCalls).toEqual(["release-a", "release-a"]);
    expect(KEY("release-a", "external")).not.toEqual(KEY("release-a", "internal"));
  });

  it("rejects a context whose release disagrees with the pinned transport release", async () => {
    const qc = client();
    const options = assembliesQueryOptions({ releaseId: "release-b", siteVariant: "external" });
    await expect(qc.fetchQuery(options)).rejects.toThrow(
      "Assembly query release differs from transport release",
    );
  });

  it("scopes chromosome reads by assembly, release and site", async () => {
    const qc = client();
    await qc.fetchQuery(
      assemblyChromosomesQueryOptions({ releaseId: "release-a", siteVariant: "external", assemblyId: 5 }),
    );
    await qc.fetchQuery(
      assemblyChromosomesQueryOptions({ releaseId: "release-a", siteVariant: "external", assemblyId: 4 }),
    );
    expect(transport.chromosomeCalls).toEqual([5, 4]);

    const key = (assemblyId: string | number | undefined, releaseId: string, site: "external" | "internal") =>
      assemblyChromosomesQueryOptions({ releaseId, siteVariant: site, assemblyId }).queryKey;
    expect(key(5, "release-a", "external")).not.toEqual(key(5, "release-b", "external"));
    expect(key(5, "release-a", "external")).not.toEqual(key(5, "release-a", "internal"));
  });

  it("does not run a chromosome read before an assembly is resolved", () => {
    const options = assemblyChromosomesQueryOptions({
      releaseId: "release-a",
      siteVariant: "external",
      assemblyId: undefined,
    });
    expect(options.enabled).toBe(false);
  });

  it("keeps `all()` a strict prefix of every scoped key so invalidation cannot go stale", async () => {
    const { queryKeys } = await import("@soymutdb/query-keys");
    const prefix = queryKeys.assemblies.all();
    for (const key of [KEY("release-a", "external"), KEY(null, "internal")]) {
      expect(key.slice(0, prefix.length)).toEqual([...prefix]);
    }
  });
});