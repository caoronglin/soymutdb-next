import { describe, expect, it } from "vitest";

import type { AssemblyContext } from "../assembly";
import { FeatureReader, normalizeGff3Line, parseGff3Attributes } from "./feature";
import { fixtureLocation, fixtureProvider } from "./test-fixtures";

const assembly: AssemblyContext = {
  key: "v5.0",
  name: "Wm82v5.0",
  refNames: ["chr01", "chr02"],
};

const FIXTURE_NAMES = ["features.gff3.gz", "features.gff3.gz.tbi"];

function makeReader(provider = fixtureProvider(FIXTURE_NAMES)): FeatureReader {
  return new FeatureReader({
    provider,
    assembly,
    trackId: "genes",
    gff: fixtureLocation("features.gff3.gz"),
    index: fixtureLocation("features.gff3.gz.tbi"),
  });
}

describe("parseGff3Attributes", () => {
  it("parses key=value pairs and decodes percent-encoding", () => {
    expect(parseGff3Attributes("ID=gene01;Name=Gene%2001")).toEqual({
      ID: "gene01",
      Name: "Gene 01",
    });
  });

  it("keeps a valueless flag and the first of repeated keys", () => {
    expect(parseGff3Attributes("ID=a;ID=b;flag")).toEqual({ ID: "a", flag: "" });
  });
});

describe("normalizeGff3Line", () => {
  it("converts 1-based inclusive coordinates to 0-based half-open", () => {
    const record = normalizeGff3Line(
      "chr01\tsrc\texon\t41\t60\t.\t+\t.\tID=exon02;Parent=mrna01",
      { assemblyKey: "v5.0" },
    );
    expect(record).toMatchObject({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 40,
      end: 60,
      type: "exon",
      id: "exon02",
      parentId: "mrna01",
      strand: "+",
    });
  });

  it("throws a parse error on a short line", () => {
    expect(() => normalizeGff3Line("chr01\tsrc\tgene", { assemblyKey: "v5.0" })).toThrowError(
      /at least 9/,
    );
  });

  it("throws a parse error on invalid coordinates", () => {
    expect(() =>
      normalizeGff3Line("chr01\tsrc\tgene\tnope\t60\t.\t+\t.\tID=g", {
        assemblyKey: "v5.0",
      }),
    ).toThrowError(/invalid coordinates/);
  });
});

describe("FeatureReader", () => {
  it("returns genes, transcripts, exons and CDS with hierarchy", async () => {
    const records = await makeReader().getFeatures({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 60,
    });
    expect(records.map((record) => record.type)).toEqual([
      "gene",
      "mRNA",
      "exon",
      "CDS",
      "exon",
    ]);
    expect(records[0]).toMatchObject({
      id: "gene01",
      name: "Gene01",
      start: 0,
      end: 60,
      strand: "+",
    });
    expect(records[1].parentId).toBe("gene01");
    expect(records[2]).toMatchObject({ id: "exon01", parentId: "mrna01", start: 0, end: 20 });
    expect(records[3]).toMatchObject({ id: "cds01", parentId: "mrna01", start: 4, end: 20, phase: 0 });
    expect(records[4]).toMatchObject({ id: "exon02", parentId: "mrna01", start: 40, end: 60 });
  });

  it("filters features to the queried window", async () => {
    const records = await makeReader().getFeatures({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 20,
    });
    expect(records.map((record) => record.id)).toEqual(["gene01", "mrna01", "exon01", "cds01"]);
  });

  it("decodes a second reference and negative strand", async () => {
    const records = await makeReader().getFeatures({
      assemblyKey: "v5.0",
      refName: "chr02",
      start: 0,
      end: 40,
    });
    expect(records).toHaveLength(1);
    expect(records[0]).toMatchObject({ id: "gene02", name: "Gene 02", strand: "-" });
  });

  it("returns no features for an empty region", async () => {
    const records = await makeReader().getFeatures({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 5,
      end: 5,
    });
    expect(records).toEqual([]);
  });

  it("rejects a cross-assembly region", async () => {
    await expect(
      makeReader().getFeatures({ assemblyKey: "v4.0", refName: "chr01", start: 0, end: 10 }),
    ).rejects.toMatchObject({ code: "assembly-mismatch" });
  });

  it("wraps a missing tabix index as a fetch error", async () => {
    const reader = makeReader(fixtureProvider(["features.gff3.gz"]));
    await expect(
      reader.getFeatures({ assemblyKey: "v5.0", refName: "chr01", start: 0, end: 10 }),
    ).rejects.toMatchObject({ code: "fetch" });
  });
});
