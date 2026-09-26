import { describe, expect, it } from "vitest";

import type { AssemblyContext } from "../assembly";
import { GenomeDataError } from "../errors";
import type { FileProvider } from "../file-provider";
import { QuantitativeReader, normalizeQuantFeatures } from "./quantitative";
import {
  FailFirstOpenProvider,
  fixtureLocation,
  fixtureProvider,
} from "./test-fixtures";

const assembly: AssemblyContext = {
  key: "v5.0",
  name: "Wm82v5.0",
  refNames: ["chr01"],
};

const FIXTURE_NAMES = ["gc_content.bw"];

function makeReader(provider: FileProvider = fixtureProvider(FIXTURE_NAMES)): QuantitativeReader {
  return new QuantitativeReader({
    provider,
    assembly,
    trackId: "coverage",
    bigWig: fixtureLocation("gc_content.bw"),
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
  // Real BigWig bytes: gc_content.bw holds chr01:0-20 = 0.4 and
  // chr01:20-40 = 0.6 (float32 on disk, hence the tolerance below).
  it("reads the two gc_content.bw intervals end to end", async () => {
    const records = await makeReader().getQuantitative({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 60,
    });
    expect(records).toHaveLength(2);
    expect(records.map((record) => [record.start, record.end])).toEqual([
      [0, 20],
      [20, 40],
    ]);
    expect(records[0]).toMatchObject({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 20,
    });
    expect(records[1]).toMatchObject({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 20,
      end: 40,
    });
    expect(records[0].score).toBeCloseTo(0.4, 6);
    expect(records[1].score).toBeCloseTo(0.6, 6);
  });

  it("filters spans to the queried window", async () => {
    const records = await makeReader().getQuantitative({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 20,
    });
    expect(records.map((record) => [record.start, record.end])).toEqual([[0, 20]]);
    expect(records[0].score).toBeCloseTo(0.4, 6);
  });

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

  it("retries the open after a failed open and then succeeds", async () => {
    const provider = new FailFirstOpenProvider(fixtureProvider(FIXTURE_NAMES));
    const reader = makeReader(provider);
    const region = { assemblyKey: "v5.0", refName: "chr01", start: 0, end: 60 };
    const first = await reader.getQuantitative(region).catch((error: unknown) => error);
    expect(first).toBeInstanceOf(GenomeDataError);
    expect(first).toMatchObject({ code: "fetch" });
    const openedAfterFailure = provider.openCount;
    await expect(reader.getQuantitative(region)).resolves.toHaveLength(2);
    expect(provider.openCount).toBeGreaterThan(openedAfterFailure);
  });

  it("maps an undecodable BigWig payload to a parse error", async () => {
    const provider = fixtureProvider([]);
    provider.add(fixtureLocation("gc_content.bw"), "not a bigwig file");
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
