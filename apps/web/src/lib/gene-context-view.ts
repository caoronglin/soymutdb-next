/**
 * Locus context for the gene detail page: a fixed ±2 kb window and the tracks
 * that fill it.
 *
 * Two coordinate conventions meet here, and mixing them is how a picture ends up
 * one base pair off or claims a gene is outside its own window:
 *
 * - the gene record and `GET /genes/region-structure` speak **1-based
 *   inclusive** (`start_pos`/`end_pos`, `gene.start`/`gene.end`);
 * - `@soymutdb/genome-view` speaks **0-based half-open** (`Region.start`
 *   inclusive, `Region.end` exclusive), because it also renders browser tracks.
 *
 * The arithmetic lives here, as pure functions, so the window is unit-testable
 * without a DOM and the component only maps records to what the renderer draws.
 */
import type { RegionGene } from "@soymutdb/api-client";
import type { SvgFeature, SvgTrack } from "@soymutdb/genome-view";

import { geneFeature } from "./locus-structure";

/** Context the gene page always shows, in base pairs on each side. */
export const GENE_CONTEXT_FLANK_BP = 2000;

/** A window in 1-based inclusive coordinates, the same space as the API. */
export interface GeneContextWindow {
  start: number;
  end: number;
}

/**
 * `gene.start_pos - flank … gene.end_pos + flank`, clamped to the chromosome.
 *
 * The lower bound clamps at 1 (there is no base 0, and the API rejects
 * `start < 1`); the upper bound clamps at `chromosomeLength` when the catalogue
 * knows it. `chromosomeLength` is optional because the length arrives with the
 * region response: the request is sent with the unclamped end, and the window is
 * re-derived from the length the API reports for that chromosome. Guessing a
 * length instead would either cut genes off the chromosome or draw empty space
 * past its end.
 */
export function geneContextWindow(
  gene: { start_pos: number; end_pos: number },
  chromosomeLength?: number | null,
): GeneContextWindow {
  const start = Math.max(1, Math.floor(gene.start_pos) - GENE_CONTEXT_FLANK_BP);
  const rawEnd = Math.floor(gene.end_pos) + GENE_CONTEXT_FLANK_BP;
  const clampedEnd =
    chromosomeLength && chromosomeLength > 0 ? Math.min(rawEnd, chromosomeLength) : rawEnd;
  // A length below the window start means the two records disagree; keep the
  // view non-degenerate rather than emitting an inverted interval.
  return { start, end: clampedEnd > start ? clampedEnd : start + 1 };
}

/** The same window in the renderer's 0-based half-open space. */
export function geneContextRegion(
  gene: { chromosome: string; start_pos: number; end_pos: number },
  window: GeneContextWindow,
  assemblyKey?: string,
): { assemblyKey: string; refName: string; start: number; end: number } {
  return {
    assemblyKey: assemblyKey ?? gene.chromosome,
    refName: gene.chromosome,
    // 1-based inclusive start `s` is 0-based inclusive `s - 1`; a 1-based
    // inclusive end is already the 0-based exclusive end.
    start: Math.max(0, window.start - 1),
    end: window.end,
  };
}

/** What the pointer is over in the locus picture. */
export type GeneContextPointKind =
  | "exon"
  | "intron"
  | "gene-body"
  | "mutation"
  | "neighbour"
  | "flank";

/**
 * The most specific drawn feature at one base pair.
 *
 * `index`/`total` are 1-based ordinals across the gene's exon union, so an
 * intron reads as "intron 2 of 3" rather than as an anonymous gap.
 */
export interface GeneContextPoint {
  kind: GeneContextPointKind;
  index?: number;
  total?: number;
  /** Neighbour accession, or the gene a flank belongs to. */
  geneId?: string;
  /** Strand-aware side of the gene, for `flank`. */
  side?: "upstream" | "downstream";
  /** The drawn mark's own label, for `mutation`. */
  label?: string;
}

export interface DescribeGeneContextPointInput {
  gene: { gene_id: string; start_pos: number; end_pos: number; strand?: string | null };
  /** The exon union exactly as drawn (merged spans, 1-based inclusive). */
  exons?: readonly GeneContextWindow[];
  /** Every other gene in the window, as the region query returned it. */
  neighbours?: readonly { gene_id: string; start: number; end: number }[];
  /** Mutation marks exactly as drawn. */
  mutations?: readonly { position: number; label: string }[];
  /**
   * Half-width, in base pairs, within which a pointer counts as on a mutation
   * mark. Zero (the default) demands an exact hit.
   *
   * A variant site is one base pair. Drawn across a whole-gene window it is a
   * fraction of a pixel wide, so an exact-hit rule makes it reportable only by
   * accident: the reader sees a mark, points at it, and the readout answers
   * "intron". Callers therefore pass half the window's bp-per-pixel here, so
   * the mark is as hittable as it is wide on screen. It stays a *snap*, not a
   * neighbourhood: the tolerance is one pixel, not one screen.
   */
  mutationToleranceBp?: number;
}

function contains(span: GeneContextWindow, bp: number): boolean {
  return bp >= span.start && bp <= span.end;
}

/**
 * Name the feature under the pointer, most specific first.
 *
 * The order is the point of the function: a base pair inside an exon is also
 * inside the gene body, inside the gene's track and inside the window, and a
 * readout that stopped at the first match would call every one of them "gene".
 * Mutation marks win over the exon they sit in because the mark is what the eye
 * is on, and a neighbour gene is more specific than "flank".
 *
 * Spans are the ones the renderer draws, not a re-derived set: the readout and
 * the picture must not disagree about where an exon starts.
 */
export function describeGeneContextPoint(
  bp: number,
  { gene, exons = [], neighbours = [], mutations = [], mutationToleranceBp = 0 }: DescribeGeneContextPointInput,
): GeneContextPoint {
  const tolerance = Number.isFinite(mutationToleranceBp) ? Math.max(0, mutationToleranceBp) : 0;
  const mutation = mutations.find(
    (site) => bp >= site.position - tolerance && bp <= site.position + 1 + tolerance,
  );
  if (mutation) return { kind: "mutation", label: mutation.label };

  const geneSpan = { start: gene.start_pos, end: gene.end_pos };
  if (contains(geneSpan, bp)) {
    const exonIndex = exons.findIndex((exon) => contains(exon, bp));
    if (exonIndex >= 0) {
      return { kind: "exon", index: exonIndex + 1, total: exons.length };
    }
    // An intron is a gap between two exons. With one exon (or none) there is no
    // intron to be in, and the honest answer is the body itself -- as it is for
    // the bases before the first exon or after the last one, which no intron
    // bounds.
    const introns = exons.length - 1;
    if (introns >= 1) {
      const ordinal = exons.filter((exon) => exon.end < bp).length;
      if (ordinal >= 1 && ordinal <= introns) {
        return { kind: "intron", index: ordinal, total: introns };
      }
    }
    return { kind: "gene-body" };
  }

  const neighbour = neighbours.find((candidate) => contains(candidate, bp));
  if (neighbour) return { kind: "neighbour", geneId: neighbour.gene_id };

  // Upstream is relative to transcription: on the minus strand the higher
  // coordinates are the 5' side. A record without a strand falls back to the
  // genomic left-to-right reading rather than guessing.
  const before = bp < geneSpan.start;
  const upstream = gene.strand === "-" ? !before : before;
  return {
    kind: "flank",
    geneId: gene.gene_id,
    side: upstream ? "upstream" : "downstream",
  };
}

export interface BuildGeneContextTracksInput {
  chromosome: string;
  /**
   * The gene the page is about, drawn at full strength. Built by the caller from
   * the detail response, which is authoritative for this gene's exon structure.
   */
  selected: SvgFeature;
  /** Every *other* gene the region query returned, drawn dimmed as context. */
  contextGenes: RegionGene[];
  /** Mutation-site marks, when the local preview endpoint answered. */
  mutationFeatures?: SvgFeature[];
  /**
   * Caller-owned lanes that describe the selected gene itself (its isoforms),
   * inserted immediately after it so they read as part of the same row group.
   */
  afterSelected?: SvgTrack[];
  labels: { selected: string; context: string; sites: string };
}

/**
 * Ruler, the selected gene, its neighbours and the mutation sites.
 *
 * The selected gene gets its own lane so "which one am I looking at" is answered
 * by position as well as by contrast: the context lane holds every other gene in
 * the window, each marked `dim` so the renderer draws it at reduced opacity. The
 * context lane is omitted entirely when the window holds nothing else, rather
 * than shipping an empty lane with a "(0)" label.
 */
export function buildGeneContextTracks({
  chromosome,
  selected,
  contextGenes,
  mutationFeatures = [],
  afterSelected = [],
  labels,
}: BuildGeneContextTracksInput): SvgTrack[] {
  const tracks: SvgTrack[] = [{ id: "ruler", label: chromosome, kind: "ruler" }];
  tracks.push({ id: "gene", label: labels.selected, kind: "feature", features: [selected] });
  tracks.push(...afterSelected);
  if (contextGenes.length > 0) {
    tracks.push({
      id: "context",
      label: labels.context,
      kind: "feature",
      features: contextGenes.map((gene) => ({ ...geneFeature(gene), dim: true })),
    });
  }
  if (mutationFeatures.length > 0) {
    tracks.push({
      id: "sites",
      label: labels.sites,
      kind: "feature",
      features: mutationFeatures,
    });
  }
  return tracks;
}