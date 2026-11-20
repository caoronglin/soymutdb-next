/**
 * The gene page's ±2 kb context window.
 *
 * The window is a contract, not a style choice: the page states that it shows
 * 2000 bp upstream and downstream, so the arithmetic has to be exactly that —
 * including at the two edges of a chromosome, where a naive `± flank` would
 * either produce base 0 or draw past the last base.
 *
 * The second half pins the other promise: *every* gene the region query returns
 * is drawn, and the gene the page is about is the one drawn at full strength.
 */
import { describe, expect, it } from "vitest";
import type { RegionGene } from "@soymutdb/api-client";

import {
  GENE_CONTEXT_FLANK_BP,
  buildGeneContextTracks,
  describeGeneContextPoint,
  geneContextRegion,
  geneContextWindow,
} from "./gene-context-view";

const labels = { selected: "Selected gene", context: "Neighbouring genes", sites: "Sites" };

function regionGene(geneId: string, start: number, end: number, strand = "+"): RegionGene {
  return {
    gene_id: geneId,
    name: null,
    chromosome: "Chr01",
    start,
    end,
    start_pos: start,
    end_pos: end,
    strand,
    biotype: "protein_coding",
    transcripts: [
      {
        id: `${geneId}.t1`,
        name: null,
        biotype: "protein_coding",
        start,
        end,
        strand,
        is_canonical: true,
        parts: [{ kind: "cds", start, end }],
      },
    ],
  };
}

describe("geneContextWindow", () => {
  it("is the gene body plus exactly 2000 bp on each side", () => {
    expect(GENE_CONTEXT_FLANK_BP).toBe(2000);
    expect(geneContextWindow({ start_pos: 5000, end_pos: 6000 })).toEqual({
      start: 3000,
      end: 8000,
    });
  });

  it("clamps the upstream edge at base 1 instead of emitting base 0", () => {
    // 1000 - 2000 would be -1000; there is no base 0 in a 1-based coordinate space.
    expect(geneContextWindow({ start_pos: 1000, end_pos: 2000 })).toEqual({
      start: 1,
      end: 4000,
    });
  });

  it("clamps the downstream edge at the chromosome length", () => {
    expect(geneContextWindow({ start_pos: 1000, end_pos: 2000 }, 2500)).toEqual({
      start: 1,
      end: 2500,
    });
    expect(geneContextWindow({ start_pos: 100_000, end_pos: 101_000 }, 200_000)).toEqual({
      start: 98_000,
      end: 103_000,
    });
  });

  it("ignores a length that does not bound the window", () => {
    // A catalogued length shorter than the gene is inconsistent data; the view
    // must stay non-degenerate instead of rendering an inverted interval.
    const window = geneContextWindow({ start_pos: 5000, end_pos: 6000 }, 500);
    expect(window.end).toBeGreaterThan(window.start);
  });

  it("hands the renderer the same window in its 0-based half-open space", () => {
    const gene = { chromosome: "Chr01", start_pos: 5000, end_pos: 6000 };
    const region = geneContextRegion(gene, geneContextWindow(gene), "Wm82 a6.v1");
    // 1-based inclusive 3000..8000 is 0-based half-open 2999..8000: the last
    // drawn base of the window is still 8000.
    expect(region).toEqual({
      assemblyKey: "Wm82 a6.v1",
      refName: "Chr01",
      start: 2999,
      end: 8000,
    });
  });
});

describe("buildGeneContextTracks", () => {
  const selected = {
    id: "Glyma.01G000100.Wm82.a6.v1",
    start: 5000,
    end: 6000,
    kind: "gene" as const,
    label: "Glyma.01G000100",
    strand: "+" as const,
  };

  it("draws every gene the region query returned, and exactly once", () => {
    const contextGenes = [
      regionGene("Glyma.01G000050", 2000, 3000),
      regionGene("Glyma.01G000200", 7000, 7500, "-"),
    ];
    const tracks = buildGeneContextTracks({
      chromosome: "Chr01",
      selected,
      contextGenes,
      labels,
    });
    const ids = tracks.flatMap((track) => (track.features ?? []).map((feature) => feature.id));
    expect(ids.sort()).toEqual(
      ["Glyma.01G000050", "Glyma.01G000100.Wm82.a6.v1", "Glyma.01G000200"].sort(),
    );
  });

  it("keeps the page's gene at full strength and dims the flanking context", () => {
    const tracks = buildGeneContextTracks({
      chromosome: "Chr01",
      selected,
      contextGenes: [regionGene("Glyma.01G000050", 2000, 3000)],
      labels,
    });
    const selectedLane = tracks.find((track) => track.id === "gene");
    const contextLane = tracks.find((track) => track.id === "context");
    expect(selectedLane?.features?.[0]).toMatchObject({ id: selected.id });
    expect(selectedLane?.features?.[0].dim).toBeUndefined();
    expect(contextLane?.features?.[0]).toMatchObject({ id: "Glyma.01G000050", dim: true });
  });

  it("omits the context lane when the window holds no other gene", () => {
    const tracks = buildGeneContextTracks({
      chromosome: "Chr01",
      selected,
      contextGenes: [],
      labels,
    });
    expect(tracks.map((track) => track.id)).toEqual(["ruler", "gene"]);
  });
});
/**
 * The pointer readout has to name the *most specific* thing under the cursor.
 * Every case below is a base pair that is simultaneously inside the window, the
 * gene's lane and — for the exon case — the gene body, so a lookup that stops at
 * the first match would label them all "gene".
 */
describe("describeGeneContextPoint", () => {
  const gene = {
    gene_id: "Glyma.01G000100",
    start_pos: 5000,
    end_pos: 5500,
    strand: "+",
  };
  // The merged exon union the renderer draws, not the transcripts it came from.
  const exons = [
    { start: 5000, end: 5100 },
    { start: 5300, end: 5500 },
  ];
  const neighbours = [{ gene_id: "Glyma.01G000050", start: 3100, end: 4000 }];
  const mutations = [{ position: 5400, label: "line-a" }];

  it("names the exon a base pair falls in, with its ordinal", () => {
    expect(describeGeneContextPoint(5050, { gene, exons })).toEqual({
      kind: "exon",
      index: 1,
      total: 2,
    });
    expect(describeGeneContextPoint(5401, { gene, exons })).toEqual({
      kind: "exon",
      index: 2,
      total: 2,
    });
  });

  it("names the intron between two exons, with its ordinal", () => {
    // Between exon 1 (ends 5100) and exon 2 (starts 5300): the first intron.
    expect(describeGeneContextPoint(5200, { gene, exons })).toEqual({
      kind: "intron",
      index: 1,
      total: 1,
    });
    const threeExons = [...exons, { start: 5600, end: 5700 }];
    expect(describeGeneContextPoint(5550, { gene: { ...gene, end_pos: 5700 }, exons: threeExons }))
      .toEqual({ kind: "intron", index: 2, total: 2 });
  });

  it("says gene body when the record has no exon structure to be in", () => {
    expect(describeGeneContextPoint(5250, { gene, exons: [] })).toEqual({ kind: "gene-body" });
    // One exon cannot bound an intron, so a gap in a single-exon gene stays body.
    expect(describeGeneContextPoint(5250, { gene, exons: [{ start: 5000, end: 5100 }] })).toEqual({
      kind: "gene-body",
    });
  });

  it("names a neighbour accession when the pointer is over another gene", () => {
    expect(describeGeneContextPoint(3500, { gene, exons, neighbours })).toEqual({
      kind: "neighbour",
      geneId: "Glyma.01G000050",
    });
  });

  it("calls the flanks upstream or downstream by transcription direction", () => {
    expect(describeGeneContextPoint(4500, { gene, exons })).toEqual({
      kind: "flank",
      geneId: gene.gene_id,
      side: "upstream",
    });
    expect(describeGeneContextPoint(6500, { gene, exons })).toEqual({
      kind: "flank",
      geneId: gene.gene_id,
      side: "downstream",
    });
    // On the minus strand the 5' side is the higher coordinate.
    const minus = { ...gene, strand: "-" };
    expect(describeGeneContextPoint(4500, { gene: minus, exons })).toMatchObject({ side: "downstream" });
    expect(describeGeneContextPoint(6500, { gene: minus, exons })).toMatchObject({ side: "upstream" });
  });

  it("prefers the mutation mark drawn in the exon it sits on", () => {
    expect(describeGeneContextPoint(5400, { gene, exons, mutations })).toEqual({
      kind: "mutation",
      label: "line-a",
    });
  });

  it("reports a one-base-pair mark the pointer can only reach by snapping", () => {
    // A site at 5400 drawn across a whole-gene window is a fraction of a pixel
    // wide. Without a tolerance the readout answers "exon"/"intron" for a mark
    // the reader can see, so the caller passes half its bp-per-pixel.
    expect(describeGeneContextPoint(5409, { gene, exons, mutations })).toEqual({
      kind: "exon",
      index: 2,
      total: 2,
    });
    expect(
      describeGeneContextPoint(5409, { gene, exons, mutations, mutationToleranceBp: 10 }),
    ).toEqual({ kind: "mutation", label: "line-a" });
  });

  it("does not let the snap radius swallow the next feature", () => {
    // The tolerance is a pixel, not a neighbourhood: past it the answer is the
    // exon again, so a reader pointing at real sequence is not told "mutation".
    expect(
      describeGeneContextPoint(5412, { gene, exons, mutations, mutationToleranceBp: 10 }),
    ).toEqual({ kind: "exon", index: 2, total: 2 });
  });
});
