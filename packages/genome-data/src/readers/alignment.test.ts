import { describe, expect, it } from "vitest";

import type { AssemblyContext } from "../assembly";
import { AlignmentReader } from "./alignment";
import { fixtureLocation, fixtureProvider } from "./test-fixtures";

const assembly: AssemblyContext = {
  key: "v5.0",
  name: "Wm82v5.0",
  refNames: ["chr01", "chr02"],
};

const FIXTURE_NAMES = ["alignment.bam", "alignment.bam.bai"];

function makeReader(provider = fixtureProvider(FIXTURE_NAMES)): AlignmentReader {
  return new AlignmentReader({
    provider,
    assembly,
    trackId: "alignments",
    bam: fixtureLocation("alignment.bam"),
    index: fixtureLocation("alignment.bam.bai"),
  });
}

describe("AlignmentReader", () => {
  it("reads the four fixture reads with coordinates and strand", async () => {
    const reader = makeReader();
    const chr01 = await reader.getAlignments({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 60,
    });
    expect(chr01.map((record) => [record.readName, record.start, record.end, record.strand])).toEqual([
      ["r1", 0, 5, "+"],
      ["r2", 9, 14, "+"],
      ["r3", 19, 24, "-"],
    ]);

    const chr02 = await reader.getAlignments({
      assemblyKey: "v5.0",
      refName: "chr02",
      start: 0,
      end: 40,
    });
    expect(chr02.map((record) => [record.readName, record.start, record.end, record.strand])).toEqual([
      ["r4", 4, 9, "+"],
    ]);
  });

  it("keeps id, read, cigar, mapq, templateLength and flags", async () => {
    const records = await makeReader().getAlignments({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 60,
    });
    expect(records[0]).toEqual({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 5,
      id: "r1:chr01:0-5",
      readName: "r1",
      read: "ACGTA",
      strand: "+",
      cigar: "5M",
      mapq: 60,
      templateLength: 0,
      flags: 0,
    });
    expect(records[2]).toMatchObject({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 19,
      end: 24,
      id: "r3:chr01:19-24",
      readName: "r3",
      read: "CCCCC",
      strand: "-",
      cigar: "5M",
      mapq: 60,
      templateLength: 0,
      flags: 16,
    });
    expect(records).toHaveLength(3);
  });

  it("returns only reads overlapping the queried window", async () => {
    const records = await makeReader().getAlignments({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 15,
    });
    expect(records.map((record) => record.readName)).toEqual(["r1", "r2"]);
  });

  it("returns no records past the last read", async () => {
    const records = await makeReader().getAlignments({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 30,
      end: 60,
    });
    expect(records).toEqual([]);
  });

  it("returns no records for an empty region without reading the file", async () => {
    const records = await makeReader(fixtureProvider([])).getAlignments({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 5,
      end: 5,
    });
    expect(records).toEqual([]);
  });

  it("rejects a cross-assembly region", async () => {
    await expect(
      makeReader().getAlignments({ assemblyKey: "v4.0", refName: "chr01", start: 0, end: 60 }),
    ).rejects.toMatchObject({ code: "assembly-mismatch" });
  });

  it("rejects an unknown reference name", async () => {
    await expect(
      makeReader().getAlignments({ assemblyKey: "v5.0", refName: "chr99", start: 0, end: 60 }),
    ).rejects.toMatchObject({ code: "assembly-mismatch" });
  });

  it("wraps a missing BAM index as a fetch error", async () => {
    const reader = makeReader(fixtureProvider(["alignment.bam"]));
    await expect(
      reader.getAlignments({ assemblyKey: "v5.0", refName: "chr01", start: 0, end: 60 }),
    ).rejects.toMatchObject({ code: "fetch" });
  });

  it("wraps an undecodable BAM payload as a fetch error", async () => {
    const provider = fixtureProvider([]);
    provider.add(fixtureLocation("alignment.bam"), "not a bam file");
    provider.add(fixtureLocation("alignment.bam.bai"), "not a bai file");
    await expect(
      makeReader(provider).getAlignments({
        assemblyKey: "v5.0",
        refName: "chr01",
        start: 0,
        end: 60,
      }),
    ).rejects.toMatchObject({ code: "fetch" });
  });

  it("reports an aborted read as an aborted error", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      makeReader().getAlignments(
        { assemblyKey: "v5.0", refName: "chr01", start: 0, end: 60 },
        { signal: controller.signal },
      ),
    ).rejects.toMatchObject({ code: "aborted" });
  });
});
