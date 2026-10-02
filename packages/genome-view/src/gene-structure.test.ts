import { describe, expect, it } from "vitest";
import { mergeExonSpans, placeStructureParts, type StructurePart } from "./gene-structure";
import type { GenomeViewport } from "./viewport";

/** 1000 bp across 1000 px makes every expected value an integer base pair. */
const viewport: GenomeViewport = {
  assemblyKey: "Gmax_880_v6.0",
  refName: "Gm01",
  start: 0,
  end: 1000,
};

const gene = { start: 100, end: 900 };
const exon = (start: number, end: number, kind: StructurePart["kind"] = "exon"): StructurePart => ({
  start,
  end,
  kind,
});

describe("placeStructureParts", () => {
  it("maps an interior exon 1:1 onto screen space", () => {
    const placed = placeStructureParts([exon(150, 250)], viewport, 1000, gene.start, gene.end);
    expect(placed).toEqual([
      { kind: "exon", start: 150, end: 250, x: 150, width: 100 },
    ]);
  });

  it("clamps an exon that overhangs its gene", () => {
    // A mis-annotated part must not smear the structure past the gene body.
    const placed = placeStructureParts([exon(50, 120)], viewport, 1000, gene.start, gene.end);
    expect(placed).toEqual([{ kind: "exon", start: 100, end: 120, x: 100, width: 20 }]);
  });

  it("drops an exon entirely outside the window", () => {
    expect(placeStructureParts([exon(1100, 1200)], viewport, 1000, 0, 5000)).toEqual([]);
  });

  it("drops a zero-length exon instead of emitting invisible markup", () => {
    expect(placeStructureParts([exon(200, 200)], viewport, 1000, gene.start, gene.end)).toEqual([]);
  });

  it("never returns a sub-pixel width, so a tiny exon stays visible", () => {
    const [placed] = placeStructureParts([exon(100, 100.2)], viewport, 1000, gene.start, gene.end);
    expect(placed.width).toBeGreaterThanOrEqual(1);
  });

  it("keeps biological order rather than re-sorting", () => {
    const placed = placeStructureParts(
      [exon(700, 750), exon(150, 200)],
      viewport,
      1000,
      gene.start,
      gene.end,
    );
    expect(placed.map((part) => part.start)).toEqual([700, 150]);
  });

  it("returns nothing for a degenerate window or width", () => {
    expect(placeStructureParts([exon(10, 20)], { ...viewport, end: 0 }, 1000, 0, 5000)).toEqual([]);
    expect(placeStructureParts([exon(10, 20)], viewport, 0, 0, 5000)).toEqual([]);
  });

  it("scales with a window narrower than the gene", () => {
    // 100 bp across 1000 px: the same exon is ten times wider.
    const zoomed: GenomeViewport = { ...viewport, start: 100, end: 200 };
    const [placed] = placeStructureParts([exon(120, 140)], zoomed, 1000, gene.start, gene.end);
    expect(placed.x).toBe(200);
    expect(placed.width).toBe(200);
  });
});

describe("mergeExonSpans", () => {
  it("merges overlapping exons into the gene's union structure", () => {
    expect(mergeExonSpans([{ start: 10, end: 20 }, { start: 15, end: 30 }])).toEqual([
      { start: 10, end: 30 },
    ]);
  });

  it("merges abutting exons", () => {
    expect(mergeExonSpans([{ start: 10, end: 20 }, { start: 20, end: 30 }])).toEqual([
      { start: 10, end: 30 },
    ]);
  });

  it("keeps a real gap as two exons", () => {
    expect(mergeExonSpans([{ start: 10, end: 20 }, { start: 25, end: 30 }])).toEqual([
      { start: 10, end: 20 },
      { start: 25, end: 30 },
    ]);
  });

  it("sorts before merging, so input order cannot change the result", () => {
    expect(mergeExonSpans([{ start: 40, end: 60 }, { start: 10, end: 30 }])).toEqual([
      { start: 10, end: 30 },
      { start: 40, end: 60 },
    ]);
  });

  it("ignores empty and inverted spans", () => {
    expect(mergeExonSpans([{ start: 20, end: 20 }, { start: 30, end: 10 }])).toEqual([]);
  });

  it("does not mutate its input", () => {
    const input = [{ start: 10, end: 20 }];
    mergeExonSpans([...input, { start: 15, end: 30 }]);
    expect(input).toEqual([{ start: 10, end: 20 }]);
  });
});
