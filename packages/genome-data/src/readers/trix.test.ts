import { describe, expect, it } from "vitest";

import { TextSearchReader } from "./trix";
import { fixtureLocation, fixtureProvider } from "./test-fixtures";

const FIXTURE_NAMES = ["genes.ix", "genes.ixx"];

function makeReader(provider = fixtureProvider(FIXTURE_NAMES)): TextSearchReader {
  return new TextSearchReader({
    provider,
    trackId: "gene-search",
    ix: fixtureLocation("genes.ix"),
    ixx: fixtureLocation("genes.ixx"),
  });
}

describe("TextSearchReader", () => {
  it("returns prefix hits with their term and payload", async () => {
    const hits = await makeReader().search("at1");
    expect(hits).toEqual([
      { id: "at1g01010", label: "chr01:1..60|gene:AT1G01010|AT1G01010" },
      { id: "at1g01020", label: "chr01:41..60|gene:AT1G01020|AT1G01020" },
    ]);
  });

  it("is case-insensitive", async () => {
    const hits = await makeReader().search("AT1");
    expect(hits.map((hit) => hit.id)).toEqual(["at1g01010", "at1g01020"]);
  });

  it("honours the limit", async () => {
    const hits = await makeReader().search("at1", 1);
    expect(hits).toHaveLength(1);
    expect(hits[0].id).toBe("at1g01010");
  });

  it("returns an empty list for an empty prefix or no match", async () => {
    await expect(makeReader().search("   ")).resolves.toEqual([]);
    await expect(makeReader().search("zzz")).resolves.toEqual([]);
    await expect(makeReader().search("at1", 0)).resolves.toEqual([]);
  });

  it("wraps a missing index as a fetch error", async () => {
    const reader = makeReader(fixtureProvider(["genes.ix"]));
    await expect(reader.search("at1")).rejects.toMatchObject({ code: "fetch" });
  });
});
