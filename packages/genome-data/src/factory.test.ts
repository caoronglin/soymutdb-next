import { describe, expect, it } from "vitest";

import type { AssemblyContext } from "./assembly";
import { GenomeDataError } from "./errors";
import { createTrackDataSource } from "./factory";
import { localLocation, uriLocation } from "./location";
import type { TrackConfig } from "./types";
import { AlignmentReader } from "./readers/alignment";
import { FeatureReader } from "./readers/feature";
import { IntervalFeatureReader } from "./readers/interval";
import { QuantitativeReader } from "./readers/quantitative";
import { SequenceReader } from "./readers/sequence";
import { VariantReader } from "./readers/variant";
import { fixtureProvider } from "./readers/test-fixtures";

const assembly: AssemblyContext = {
  key: "v5.0",
  name: "Wm82v5.0",
  refNames: ["chr01", "chr02"],
};

function track(overrides: Partial<TrackConfig> & { type: string; adapter?: unknown }): TrackConfig {
  return {
    trackId: "track",
    name: "Track",
    assemblyNames: ["v5.0"],
    ...overrides,
  } as TrackConfig;
}

function options(provider = fixtureProvider([])) {
  return { provider, assemblies: [assembly] };
}

describe("createTrackDataSource", () => {
  it("builds a ReferenceSequenceTrack source", () => {
    const source = createTrackDataSource(
      track({
        type: "ReferenceSequenceTrack",
        adapter: {
          type: "BgzipFastaAdapter",
          fastaLocation: "memory://reference.fa.gz",
          faiLocation: { uri: "memory://reference.fa.gz.fai", locationType: "UriLocation" },
          gziLocation: { uri: "memory://reference.fa.gz.gzi", locationType: "UriLocation" },
        },
      }),
      options(),
    );
    expect(source.kind).toBe("reference-sequence");
    expect(source.trackId).toBe("track");
    expect(source.assemblyKey).toBe("v5.0");
    if (source.kind !== "reference-sequence") throw new Error("unreachable");
    expect(source.reader).toBeInstanceOf(SequenceReader);
  });

  it("builds a VariantTrack source and resolves the tabix index location", async () => {
    const source = createTrackDataSource(
      track({
        type: "VariantTrack",
        adapter: {
          type: "VcfTabixAdapter",
          vcfGzLocation: "memory://variants.vcf.gz",
          index: { indexType: "TBI", location: { uri: "memory://variants.vcf.gz.tbi" } },
        },
      }),
      options(fixtureProvider(["variants.vcf.gz", "variants.vcf.gz.tbi"])),
    );
    expect(source.kind).toBe("variant");
    if (source.kind !== "variant") throw new Error("unreachable");
    expect(source.reader).toBeInstanceOf(VariantReader);
    const records = await source.reader.getVariants({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 60,
    });
    expect(records).toHaveLength(6);
  });

  it("builds a FeatureTrack source for a GFF3 adapter", async () => {
    const source = createTrackDataSource(
      track({
        type: "FeatureTrack",
        adapter: {
          type: "Gff3TabixAdapter",
          gffGzLocation: { uri: "memory://features.gff3.gz", locationType: "UriLocation" },
          index: { indexType: "TBI", location: { uri: "memory://features.gff3.gz.tbi" } },
        },
      }),
      options(fixtureProvider(["features.gff3.gz", "features.gff3.gz.tbi"])),
    );
    expect(source.kind).toBe("feature");
    if (source.kind !== "feature") throw new Error("unreachable");
    expect(source.reader).toBeInstanceOf(FeatureReader);
    const records = await source.reader.getFeatures({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 60,
    });
    expect(records.map((record) => record.id)).toEqual(
      ["gene01", "mrna01", "exon01", "cds01", "exon02"],
    );
  });

  it("builds an interval source for a bigBed feature adapter", () => {
    const source = createTrackDataSource(
      track({
        type: "FeatureTrack",
        adapter: {
          type: "BigBedAdapter",
          bigBedLocation: { uri: "memory://repeats.bb", locationType: "UriLocation" },
        },
      }),
      options(),
    );
    expect(source.kind).toBe("interval");
    if (source.kind !== "interval") throw new Error("unreachable");
    expect(source.reader).toBeInstanceOf(IntervalFeatureReader);
  });

  it("builds a QuantitativeTrack source and accepts a local path location", () => {
    const source = createTrackDataSource(
      track({
        type: "QuantitativeTrack",
        adapter: {
          type: "BigWigAdapter",
          bigWigLocation: { localPath: "/data/coverage.bw", locationType: "LocalPathLocation" },
        },
      }),
      options(),
    );
    expect(source.kind).toBe("quantitative");
    if (source.kind !== "quantitative") throw new Error("unreachable");
    expect(source.reader).toBeInstanceOf(QuantitativeReader);
    expect(localLocation("/data/coverage.bw")).toEqual({ kind: "local", path: "/data/coverage.bw" });
  });

  it("resolves an assembly by display name", () => {
    const source = createTrackDataSource(
      track({
        type: "QuantitativeTrack",
        assemblyNames: ["Wm82v5.0"],
        adapter: { type: "BigWigAdapter", bigWigLocation: uriLocation("memory://a.bw") },
      }),
      options(),
    );
    expect(source.assemblyKey).toBe("v5.0");
  });

  it("rejects an unknown track type", () => {
    expect(() => createTrackDataSource(track({ type: "GeneTrack" }), options())).toThrowError(
      GenomeDataError,
    );
    try {
      createTrackDataSource(track({ type: "GeneTrack" }), options());
    } catch (error) {
      expect((error as GenomeDataError).code).toBe("unsupported-type");
    }
  });

  it("builds an AlignmentsTrack source for a BamAdapter and reads alignments", async () => {
    const source = createTrackDataSource(
      track({
        type: "AlignmentsTrack",
        adapter: {
          type: "BamAdapter",
          bamLocation: "memory://alignment.bam",
          index: { indexType: "BAI", location: { uri: "memory://alignment.bam.bai" } },
        },
      }),
      options(fixtureProvider(["alignment.bam", "alignment.bam.bai"])),
    );
    expect(source.kind).toBe("alignment");
    expect(source.trackId).toBe("track");
    expect(source.assemblyKey).toBe("v5.0");
    if (source.kind !== "alignment") throw new Error("unreachable");
    expect(source.reader).toBeInstanceOf(AlignmentReader);
    const records = await source.reader.getAlignments({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 60,
    });
    expect(records.map((record) => record.readName)).toEqual(["r1", "r2", "r3"]);
  });

  it("rejects an AlignmentsTrack with a non-Bam adapter", () => {
    try {
      createTrackDataSource(
        track({
          type: "AlignmentsTrack",
          adapter: { type: "CramAdapter", cramLocation: "memory://alignment.cram" },
        }),
        options(),
      );
      throw new Error("expected createTrackDataSource to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(GenomeDataError);
      expect((error as GenomeDataError).code).toBe("unsupported-type");
    }
  });

  it("rejects an AlignmentsTrack bound to an unknown assembly", () => {
    try {
      createTrackDataSource(
        track({
          type: "AlignmentsTrack",
          assemblyNames: ["v4.0"],
          adapter: {
            type: "BamAdapter",
            bamLocation: "memory://alignment.bam",
            index: "memory://alignment.bam.bai",
          },
        }),
        options(),
      );
      throw new Error("expected createTrackDataSource to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(GenomeDataError);
      expect((error as GenomeDataError).code).toBe("assembly-mismatch");
    }
  });

  it("rejects an unsupported adapter for a known track type", () => {
    try {
      createTrackDataSource(
        track({ type: "ReferenceSequenceTrack", adapter: { type: "TwoBitAdapter" } }),
        options(),
      );
      throw new Error("expected createTrackDataSource to throw");
    } catch (error) {
      expect((error as GenomeDataError).code).toBe("unsupported-type");
    }
  });

  it("rejects a track with no adapter", () => {
    try {
      createTrackDataSource(track({ type: "VariantTrack" }), options());
      throw new Error("expected createTrackDataSource to throw");
    } catch (error) {
      expect((error as GenomeDataError).code).toBe("unsupported-type");
    }
  });

  it("rejects a missing required location", () => {
    try {
      createTrackDataSource(
        track({
          type: "ReferenceSequenceTrack",
          adapter: {
            type: "BgzipFastaAdapter",
            fastaLocation: "memory://reference.fa.gz",
            faiLocation: "memory://reference.fa.gz.fai",
          },
        }),
        options(),
      );
      throw new Error("expected createTrackDataSource to throw");
    } catch (error) {
      expect((error as GenomeDataError).code).toBe("unsupported-type");
    }
  });

  it("rejects a track bound to an unknown assembly", () => {
    try {
      createTrackDataSource(
        track({
          type: "QuantitativeTrack",
          assemblyNames: ["v9.0"],
          adapter: { type: "BigWigAdapter", bigWigLocation: "memory://a.bw" },
        }),
        options(),
      );
      throw new Error("expected createTrackDataSource to throw");
    } catch (error) {
      expect((error as GenomeDataError).code).toBe("assembly-mismatch");
    }
  });
});
