/**
 * Gene-structure geometry for the genome view.
 *
 * The visual grammar here follows the primer project's `geneStructure.js`
 * design (2026-09-10): a gene is drawn as its exon boxes sitting on an intron
 * line, and strand is carried by an arrowhead rather than by a label alone.
 * The arithmetic is re-derived for this renderer — this module owns screen
 * placement for exon parts, which the primer version leaves inline in its
 * component, so that both the TypeScript and Python renderers can share one
 * definition of "where does this exon go".
 *
 * All intervals remain 0-based half-open, like the rest of the viewport layer.
 */
import type { GenomeViewport } from "./viewport";
import { clipToRegion } from "./track-layout";

/** A half-open interval in template coordinates. */
export interface Interval {
  start: number;
  end: number;
}

/** Which part of a gene an exon is annotated as. */
export type StructurePartKind = "exon" | "cds" | "utr5" | "utr3";

/** Sub-structure drawn inside a feature's lane. */
export interface StructurePart extends Interval {
  kind: StructurePartKind;
}

/** A part placed on screen, in the same space as a track's x offsets. */
export interface PlacedPart {
  kind: StructurePartKind;
  start: number;
  end: number;
  x: number;
  width: number;
}

/**
 * Map a feature's exon parts into screen space for one lane.
 *
 * Parts are clipped to the viewport and dropped when they fall outside it, so a
 * deeply zoomed gene does not pay for its whole exon list. Parts that survive
 * keep their biological order, which is what lets the renderer draw them
 * left-to-right without sorting.
 */
export function placeStructureParts(
  parts: readonly StructurePart[],
  viewport: GenomeViewport,
  widthPx: number,
  geneStart: number,
  geneEnd: number,
): PlacedPart[] {
  const span = viewport.end - viewport.start;
  if (!Number.isFinite(span) || span <= 0 || !Number.isFinite(widthPx) || widthPx <= 0) {
    return [];
  }
  const scale = widthPx / span;
  const placed: PlacedPart[] = [];
  for (const part of parts) {
    // An exon with no recorded extent would render as a zero-width speck; skip
    // it rather than emit invisible markup that still costs bytes.
    if (!(part.end > part.start)) continue;
    // Never let an exon escape its gene: a mis-annotated part must not smear
    // the structure across the lane.
    const bounded = clipToRegion(
      { start: Math.max(part.start, geneStart), end: Math.min(part.end, geneEnd) },
      viewport,
    );
    if (!bounded) continue;
    placed.push({
      kind: part.kind,
      start: bounded.start,
      end: bounded.end,
      x: (bounded.start - viewport.start) * scale,
      width: Math.max(1, (bounded.end - bounded.start) * scale),
    });
  }
  return placed;
}

/**
 * Exon boxes for a gene, derived from its transcripts when no explicit parts
 * were supplied.
 *
 * Exons from several isoforms are merged only when they overlap or abut, which
 * is the union of the gene's exon structure rather than a fabricated single
 * transcript. Overlapping-but-distinct exons stay separate; the caller draws
 * them as one row, which is what makes an isoform-rich gene readable.
 */
export function mergeExonSpans(intervals: readonly Interval[]): Interval[] {
  const ordered = intervals
    .filter((interval) => interval.end > interval.start)
    .map((interval) => ({ start: interval.start, end: interval.end }))
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const merged: Interval[] = [];
  for (const span of ordered) {
    const last = merged[merged.length - 1];
    if (last && span.start <= last.end) {
      last.end = Math.max(last.end, span.end);
      continue;
    }
    merged.push({ ...span });
  }
  return merged;
}
