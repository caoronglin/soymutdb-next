import { describe, expect, it } from "vitest";

import {
  buildLocusTracks,
  geneFeature,
  locusWindow,
  pickRepresentativeTranscript,
  shortGeneLabel,
} from "./locus-structure";
import type { RegionGene, RegionTranscript } from "@soymutdb/api-client";

function transcript(over: Partial<RegionTranscript> = {}): RegionTranscript {
  return {
    id: "tx1",
    name: null,
    biotype: "mRNA",
    start: 100,
    end: 900,
    strand: "+",
    is_canonical: false,
    parts: [{ kind: "cds", start: 200, end: 300 }],
    ...over,
  };
}

function gene(over: Partial<RegionGene> = {}): RegionGene {
  return {
    gene_id: "Glyma.01G000100.Wm82.a6.v1",
    name: null,
    chromosome: "Gm01",
    start: 100,
    end: 900,
    start_pos: 100,
    end_pos: 900,
    strand: "+",
    biotype: "protein_coding",
    transcripts: [transcript()],
    ...over,
  };
}

describe("pickRepresentativeTranscript", () => {
  it("prefers the annotation's canonical transcript", () => {
    const canonical = transcript({ id: "canonical", is_canonical: true, parts: [] });
    const rich = transcript({
      id: "rich",
      parts: [
        { kind: "cds", start: 1, end: 2 },
        { kind: "cds", start: 3, end: 4 },
        { kind: "cds", start: 5, end: 6 },
      ],
    });
    expect(pickRepresentativeTranscript([rich, canonical])?.id).toBe("canonical");
  });

  it("falls back to the transcript with the most segments", () => {
    const sparse = transcript({ id: "sparse", parts: [{ kind: "cds", start: 1, end: 2 }] });
    const rich = transcript({
      id: "rich",
      parts: [
        { kind: "cds", start: 1, end: 2 },
        { kind: "utr3", start: 3, end: 4 },
      ],
    });
    expect(pickRepresentativeTranscript([sparse, rich])?.id).toBe("rich");
  });

  it("returns null for a gene with no transcripts", () => {
    expect(pickRepresentativeTranscript([])).toBeNull();
  });
});

describe("geneFeature", () => {
  it("carries the CDS and UTR segments through with their kinds intact", () => {
    const feature = geneFeature(
      gene({
        transcripts: [
          transcript({
            parts: [
              { kind: "cds", start: 200, end: 300 },
              { kind: "utr5", start: 100, end: 199 },
              { kind: "utr3", start: 800, end: 900 },
            ],
          }),
        ],
      }),
    );

    expect(feature.parts).toEqual([
      { start: 200, end: 300, kind: "cds" },
      { start: 100, end: 199, kind: "utr5" },
      { start: 800, end: 900, kind: "utr3" },
    ]);
  });

  it("draws no parts when the gene has no structure on record", () => {
    // Not the same as "no gene": the renderer falls back to a body bar, and
    // that fallback must stay reachable.
    expect(geneFeature(gene({ transcripts: [] })).parts).toEqual([]);
  });

  it("normalises an unexpected strand to plus rather than emitting it", () => {
    expect(geneFeature(gene({ strand: "?" })).strand).toBe("+");
    expect(geneFeature(gene({ strand: "-" })).strand).toBe("-");
  });
});

describe("shortGeneLabel", () => {
  it("drops the annotation-version suffix", () => {
    expect(shortGeneLabel("Glyma.01G015400.Wm82.a6.v1")).toBe("Glyma.01G015400");
  });

  it("leaves an accession without a version suffix alone", () => {
    expect(shortGeneLabel("Glyma.01G000100")).toBe("Glyma.01G000100");
    expect(shortGeneLabel("AT1G01010.1")).toBe("AT1G01010.1");
  });

  it("keeps a dotted prefix intact when there is no version tail", () => {
    // Only the third dot onward is treated as a version suffix.
    expect(shortGeneLabel("Zm00001d.2.1.1")).toBe("Zm00001d.2");
  });
});

describe("buildLocusTracks", () => {
  it("leads with the ruler and always has a gene lane", () => {
    const tracks = buildLocusTracks({ chromosome: "Gm01", genes: [gene()], spanBp: 20_000 });
    expect(tracks.map((track) => track.id)).toEqual(["ruler", "genes"]);
    expect(tracks[0].kind).toBe("ruler");
  });

  it("omits the marker lane entirely when there are no markers", () => {
    const tracks = buildLocusTracks({ chromosome: "Gm01", genes: [], spanBp: 20_000 });
    expect(tracks.some((track) => track.id === "markers")).toBe(false);
  });

  it("gives a single-base marker a visible footprint in a wide window", () => {
    const tracks = buildLocusTracks({
      chromosome: "Gm01",
      genes: [],
      markers: [{ position: 1_563_650, label: "SOYTE1M-Gm01-1563650" }],
      spanBp: 20_000,
    });
    const marker = tracks.find((track) => track.id === "markers")?.features?.[0];
    // 0.4% of 20 kb = 80 bp; a 1 bp mark would be a sub-pixel sliver.
    expect(marker?.end).toBe(1_563_650 + 80);
  });

  it("renders every gene in the window, not just the first", () => {
    const tracks = buildLocusTracks({
      chromosome: "Gm01",
      genes: [gene({ gene_id: "g1" }), gene({ gene_id: "g2" }), gene({ gene_id: "g3" })],
      spanBp: 20_000,
    });
    expect(tracks.find((t) => t.id === "genes")?.features).toHaveLength(3);
  });
});

describe("locusWindow", () => {
  it("centres the site with the requested flank on each side", () => {
    expect(locusWindow(1_563_650, 10_000, 59_600_650)).toEqual({
      start: 1_553_650,
      end: 1_573_650,
    });
  });

  it("clamps to the chromosome start instead of going negative", () => {
    const window = locusWindow(500, 10_000, 59_600_650);
    expect(window.start).toBe(1);
    expect(window.end).toBe(10_500);
  });

  it("clamps to the chromosome end", () => {
    const window = locusWindow(59_600_000, 10_000, 59_600_650);
    expect(window.end).toBe(59_600_650);
  });

  it("widens a zero flank to one base so the window is never empty", () => {
    // The API rejects `end <= start` with a 422, so a degenerate request must be
    // repaired here rather than round-tripped into an error page.
    expect(locusWindow(1_000, 0, 59_600_650)).toEqual({ start: 1_000, end: 1_001 });
  });

  it("does not clamp when the chromosome length is unknown", () => {
    expect(locusWindow(500, 10_000, undefined)).toEqual({ start: 1, end: 10_500 });
  });
});
