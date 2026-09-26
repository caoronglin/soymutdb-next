import { describe, expect, it } from "vitest";

import type { AssemblyContext } from "../assembly";
import { GenomeDataError } from "../errors";
import { SequenceReader } from "./sequence";
import { fixtureLocation, fixtureProvider } from "./test-fixtures";

const assembly: AssemblyContext = {
  key: "v5.0",
  name: "Wm82v5.0",
  refNames: ["chr01", "chr02"],
  refNameAliases: { "1": "chr01" },
};

function makeReader(provider = fixtureProvider(FIXTURE_NAMES)): SequenceReader {
  return new SequenceReader({
    provider,
    assembly,
    trackId: "refseq",
    fasta: fixtureLocation("reference.fa.gz"),
    fai: fixtureLocation("reference.fa.gz.fai"),
    gzi: fixtureLocation("reference.fa.gz.gzi"),
  });
}

const FIXTURE_NAMES = [
  "reference.fa.gz",
  "reference.fa.gz.fai",
  "reference.fa.gz.gzi",
];

describe("SequenceReader", () => {
  it("reports chrom sizes from the FAI", async () => {
    const reader = makeReader();
    await expect(reader.getChromSizes()).resolves.toEqual([
      { refName: "chr01", size: 60 },
      { refName: "chr02", size: 40 },
    ]);
    await expect(reader.getSequenceNames()).resolves.toEqual(["chr01", "chr02"]);
  });

  it("reads a 0-based half-open region", async () => {
    const reader = makeReader();
    await expect(
      reader.getSequence({ assemblyKey: "v5.0", refName: "chr01", start: 0, end: 4 }),
    ).resolves.toEqual({ assemblyKey: "v5.0", refName: "chr01", start: 0, bases: "ACGT" });
  });

  it("crosses FASTA line boundaries", async () => {
    const reader = makeReader();
    const chunk = await reader.getSequence({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 18,
      end: 22,
    });
    expect(chunk.bases).toBe("GTAC");
  });

  it("resolves a reference alias inside the assembly", async () => {
    const reader = makeReader();
    const chunk = await reader.getSequence({
      assemblyKey: "v5.0",
      refName: "1",
      start: 0,
      end: 2,
    });
    expect(chunk.refName).toBe("chr01");
    expect(chunk.bases).toBe("AC");
  });

  it("returns an empty chunk for an empty region", async () => {
    const reader = makeReader();
    const chunk = await reader.getSequence({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 10,
      end: 10,
    });
    expect(chunk).toEqual({ assemblyKey: "v5.0", refName: "chr01", start: 10, bases: "" });
  });

  it("clamps a region past the end of the contig", async () => {
    const reader = makeReader();
    const chunk = await reader.getSequence({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 58,
      end: 70,
    });
    expect(chunk.bases).toBe("GT");
  });

  it("rejects a cross-assembly region", async () => {
    const reader = makeReader();
    await expect(
      reader.getSequence({ assemblyKey: "v4.0", refName: "chr01", start: 0, end: 4 }),
    ).rejects.toMatchObject({ code: "assembly-mismatch" });
  });

  it("rejects an unknown reference name", async () => {
    const reader = makeReader();
    await expect(
      reader.getSequence({ assemblyKey: "v5.0", refName: "chr99", start: 0, end: 4 }),
    ).rejects.toMatchObject({ code: "assembly-mismatch" });
  });

  it("rejects a malformed region", async () => {
    const reader = makeReader();
    await expect(
      reader.getSequence({ assemblyKey: "v5.0", refName: "chr01", start: -1, end: 4 }),
    ).rejects.toBeInstanceOf(GenomeDataError);
  });

  it("wraps a missing file as a fetch error", async () => {
    const reader = makeReader(fixtureProvider(["reference.fa.gz", "reference.fa.gz.fai"]));
    await expect(reader.getChromSizes()).rejects.toMatchObject({ code: "fetch" });
  });
});
