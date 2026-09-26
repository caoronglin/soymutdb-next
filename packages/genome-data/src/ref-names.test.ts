import { describe, expect, it } from "vitest";

import { resolveRefName, type AssemblyContext } from "./assembly";
import type { FileProvider } from "./file-provider";
import type { GenomeLocation } from "./location";
import { AssemblyRefNameLoader } from "./ref-names";
import { fixtureBytes, fixtureLocation, fixtureProvider } from "./readers/test-fixtures";

const FIXTURE_NAMES = [
  "reference.fa.gz",
  "reference.fa.gz.fai",
  "reference.fa.gz.gzi",
];

const assembly: AssemblyContext = {
  key: "v5.0",
  name: "Wm82v5.0",
};

/** Wrap a provider so tests can count how often a handle is opened. */
function countingProvider(inner: FileProvider): { provider: FileProvider; opens: () => number } {
  let opens = 0;
  return {
    provider: {
      async open(location: GenomeLocation) {
        opens += 1;
        return inner.open(location);
      },
    },
    opens: () => opens,
  };
}

function makeLoader(provider: FileProvider): AssemblyRefNameLoader {
  return new AssemblyRefNameLoader({
    provider,
    assembly,
    trackId: "refseq",
    fasta: fixtureLocation("reference.fa.gz"),
    fai: fixtureLocation("reference.fa.gz.fai"),
    gzi: fixtureLocation("reference.fa.gz.gzi"),
  });
}

describe("AssemblyRefNameLoader", () => {
  it("loads the assembly's full reference-name list from the FASTA index", async () => {
    const loader = makeLoader(fixtureProvider(FIXTURE_NAMES));
    await expect(loader.load(["chr01"])).resolves.toEqual(["chr01", "chr02"]);
    expect(loader.isLoaded).toBe(true);
    expect(loader.cached).toEqual(["chr01", "chr02"]);
  });

  it("populates AssemblyContext.refNames so non-viewport references resolve", async () => {
    const loader = makeLoader(fixtureProvider(FIXTURE_NAMES));
    const refNames = await loader.load(["chr01"]);
    const context: AssemblyContext = { ...assembly, refNames: [...refNames] };
    expect(resolveRefName(context, "chr02")).toBe("chr02");
    expect(() => resolveRefName(context, "chr99")).toThrow(/Unknown reference/);
  });

  it("reads the index only once across repeated loads", async () => {
    const inner = fixtureProvider(FIXTURE_NAMES);
    const { provider, opens } = countingProvider(inner);
    const loader = makeLoader(provider);
    await loader.load();
    const afterFirst = opens();
    await expect(loader.load()).resolves.toEqual(["chr01", "chr02"]);
    expect(opens()).toBe(afterFirst);
    expect(afterFirst).toBeGreaterThan(0);
  });

  it("falls back instead of throwing when the index cannot be read", async () => {
    // Missing .gzi: the underlying open rejects, and the loader must absorb it.
    const loader = makeLoader(fixtureProvider(["reference.fa.gz", "reference.fa.gz.fai"]));
    await expect(loader.load(["chr01"])).resolves.toEqual(["chr01"]);
    expect(loader.isLoaded).toBe(false);
    expect(loader.cached).toBeNull();
  });

  it("returns an empty list when loading fails and no fallback is given", async () => {
    const loader = makeLoader(fixtureProvider([]));
    await expect(loader.load()).resolves.toEqual([]);
  });

  it("retries after a failed load and then caches the successful list", async () => {
    const provider = fixtureProvider(["reference.fa.gz", "reference.fa.gz.fai"]);
    const loader = makeLoader(provider);
    await expect(loader.load(["chr01"])).resolves.toEqual(["chr01"]);
    expect(loader.isLoaded).toBe(false);

    provider.add(fixtureLocation("reference.fa.gz.gzi"), fixtureBytes("reference.fa.gz.gzi"));
    await expect(loader.load(["chr01"])).resolves.toEqual(["chr01", "chr02"]);
    expect(loader.isLoaded).toBe(true);
  });
});
