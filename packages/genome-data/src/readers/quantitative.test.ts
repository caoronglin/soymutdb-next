import { describe, expect, it } from "vitest";

import type { AssemblyContext } from "../assembly";
import { QuantitativeReader, normalizeQuantFeatures } from "./quantitative";
import { fixtureLocation, fixtureProvider } from "./test-fixtures";

const assembly: AssemblyContext = {
  key: "v5.0",
  name: "Wm82v5.0",
  refNames: ["chr01"],
};

function makeReader(provider = fixtureProvider([])): QuantitativeReader {
  return new QuantitativeReader({
    provider,
    assembly,
    trackId: "coverage",
    bigWig: fixtureLocation("coverage.bw"),
  });
}

describe("normalizeQuantFeatures", () => {
  it("maps spans to assembly-scoped quant records", () => {
    const records = normalizeQuantFeatures(
      [
        { chromId: 0, start: 10, end: 20, score: 1.5 },
        { chromId: 0, start: 20, end: 30 },
      ],
      "v5.0",
      "chr01",
    );
    expect(records).toEqual([
      { assemblyKey: "v5.0", refName: "chr01", start: 10, end: 20, score: 1.5 },
      { assemblyKey: "v5.0", refName: "chr01", start: 20, end: 30, score: 0 },
    ]);
  });
});

describe("QuantitativeReader", () => {
  it("rejects a cross-assembly region", async () => {
    await expect(
      makeReader().getQuantitative({ assemblyKey: "v4.0", refName: "chr01", start: 0, end: 10 }),
    ).rejects.toMatchObject({ code: "assembly-mismatch" });
  });

  it("returns no records for an empty region without reading the file", async () => {
    const records = await makeReader(fixtureProvider([])).getQuantitative({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 5,
      end: 5,
    });
    expect(records).toEqual([]);
  });

  it("wraps a missing BigWig file as a fetch error", async () => {
    await expect(
      makeReader(fixtureProvider([])).getQuantitative({
        assemblyKey: "v5.0",
        refName: "chr01",
        start: 0,
        end: 10,
      }),
    ).rejects.toMatchObject({ code: "fetch" });
  });

  // No offline BigWig writer exists in this repo, so the fixture directory has
  // no .bw file. A garbage payload still exercises BigWig header parsing and
  // the reader error mapping; byte-exact span assertions live in
  // normalizeQuantFeatures above.
  it("maps an undecodable BigWig payload to a parse error", async () => {
    const provider = fixtureProvider([]);
    provider.add(fixtureLocation("coverage.bw"), "not a bigwig file");
    await expect(
      makeReader(provider).getQuantitative({
        assemblyKey: "v5.0",
        refName: "chr01",
        start: 0,
        end: 10,
      }),
    ).rejects.toMatchObject({ code: "parse" });
  });
});
