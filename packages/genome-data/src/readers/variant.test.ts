import VCF from "@gmod/vcf";
import { describe, expect, it } from "vitest";

import type { AssemblyContext } from "../assembly";
import { VariantReader } from "./variant";
import {
  classifyAllele,
  classifyVariantKind,
  isBreakendAllele,
  isSymbolicAllele,
  normalizeVariantLine,
  variantEnd,
} from "./variant";
import { fixtureLocation, fixtureProvider, fixtureText } from "./test-fixtures";

const assembly: AssemblyContext = {
  key: "v5.0",
  name: "Wm82v5.0",
  refNames: ["chr01", "chr02"],
};

const FIXTURE_NAMES = ["variants.vcf.gz", "variants.vcf.gz.tbi"];

function makeParser(): VCF {
  const header = fixtureText("variants.vcf")
    .split("\n")
    .filter((line) => line.startsWith("#"))
    .join("\n");
  return new VCF({ header });
}

function makeReader(provider = fixtureProvider(FIXTURE_NAMES)): VariantReader {
  return new VariantReader({
    provider,
    assembly,
    trackId: "variants",
    vcf: fixtureLocation("variants.vcf.gz"),
    index: fixtureLocation("variants.vcf.gz.tbi"),
  });
}

describe("classifyAllele", () => {
  it("classifies length-based alleles", () => {
    expect(classifyAllele("A", "T")).toBe("snv");
    expect(classifyAllele("ACGT", "AGGT")).toBe("mnv");
    expect(classifyAllele("A", "AT")).toBe("ins");
    expect(classifyAllele("ACGT", "A")).toBe("del");
  });

  it("classifies symbolic and breakend alleles as sv", () => {
    expect(isSymbolicAllele("<DEL>")).toBe(true);
    expect(isBreakendAllele("N]chr02:30]")).toBe(true);
    expect(classifyAllele("N", "<DEL>")).toBe("sv");
    expect(classifyAllele("N", "N[chr02:30[")).toBe("sv");
  });

  it("falls back to other for spanning-deletion and unknown alleles", () => {
    expect(classifyAllele("A", "*")).toBe("other");
    expect(classifyAllele("", "A")).toBe("other");
  });
});

describe("classifyVariantKind", () => {
  it("summarizes multi-allelic records", () => {
    expect(classifyVariantKind("A", ["T"])).toBe("snv");
    expect(classifyVariantKind("A", ["T", "G"])).toBe("snv");
    expect(classifyVariantKind("A", ["T", "AT"])).toBe("other");
    expect(classifyVariantKind("A", ["T", "<DEL>"])).toBe("sv");
    expect(classifyVariantKind("A", [])).toBe("other");
  });
});

describe("variantEnd", () => {
  it("uses the reference length by default", () => {
    expect(variantEnd(9, "A")).toBe(10);
    expect(variantEnd(4, "ACGT")).toBe(8);
  });

  it("honours a larger INFO/END", () => {
    expect(variantEnd(19, "N", { END: 40 })).toBe(40);
    expect(variantEnd(19, "N", { END: 15 })).toBe(20);
  });
});

describe("normalizeVariantLine", () => {
  it("converts 1-based POS to 0-based half-open", () => {
    const record = normalizeVariantLine("chr01\t5\t.\tACGT\tA\t40\tPASS\tDP=7", {
      parser: makeParser(),
      assemblyKey: "v5.0",
    });
    expect(record).toMatchObject({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 4,
      end: 8,
      ref: "ACGT",
      alt: ["A"],
      kind: "del",
      quality: 40,
    });
  });

  it("throws a parse error on a malformed POS", () => {
    expect(() =>
      normalizeVariantLine("chr01\tnope\t.\tA\tT\t.\t.\t.", {
        parser: makeParser(),
        assemblyKey: "v5.0",
      }),
    ).toThrowError(/invalid POS/);
  });
});

describe("VariantReader", () => {
  it("reads every record in a region with 0-based coordinates", async () => {
    const records = await makeReader().getVariants({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 60,
    });
    expect(records.map((record) => record.id)).toEqual([
      "rs1",
      "chr01:4-8:ACGT>A",
      "chr01:9-10:A>AT",
      "chr01:14-18:ACGT>AGGT",
      "chr01:19-40:N><DEL>",
      "chr01:49-50:N>N]chr02:30]",
    ]);
    expect(records.map((record) => record.kind)).toEqual([
      "snv",
      "del",
      "ins",
      "mnv",
      "sv",
      "sv",
    ]);
    expect(records[0]).toMatchObject({ start: 0, end: 1, ref: "A", alt: ["T"], quality: 50 });
  });

  it("filters records to the queried window", async () => {
    const records = await makeReader().getVariants({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 20,
    });
    expect(records).toHaveLength(5);
    expect(records.at(-1)).toMatchObject({ start: 19, end: 40, kind: "sv" });
  });

  it("returns no records for an empty region", async () => {
    const records = await makeReader().getVariants({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 10,
      end: 10,
    });
    expect(records).toEqual([]);
  });

  it("reads a second reference in the same assembly", async () => {
    const records = await makeReader().getVariants({
      assemblyKey: "v5.0",
      refName: "chr02",
      start: 0,
      end: 40,
    });
    expect(records).toHaveLength(1);
    expect(records[0]).toMatchObject({ id: "rs2", start: 2, end: 3, kind: "snv" });
  });

  it("rejects a cross-assembly region without touching the file", async () => {
    await expect(
      makeReader().getVariants({ assemblyKey: "v4.0", refName: "chr01", start: 0, end: 10 }),
    ).rejects.toMatchObject({ code: "assembly-mismatch" });
  });

  it("rejects an unknown reference name", async () => {
    await expect(
      makeReader().getVariants({ assemblyKey: "v5.0", refName: "chr99", start: 0, end: 10 }),
    ).rejects.toMatchObject({ code: "assembly-mismatch" });
  });

  it("wraps a missing tabix index as a fetch error", async () => {
    const reader = makeReader(fixtureProvider(["variants.vcf.gz"]));
    await expect(
      reader.getVariants({ assemblyKey: "v5.0", refName: "chr01", start: 0, end: 10 }),
    ).rejects.toMatchObject({ code: "fetch" });
  });
});
