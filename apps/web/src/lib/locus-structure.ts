/**
 * Locus view — turn a region query into the tracks the genome view draws.
 *
 * Kept out of the route component so the mapping is unit-testable without a
 * browser: the interesting decisions (which transcript represents a gene, how
 * CDS/UTR segments are carried into a feature) are pure functions of the API
 * response, and a wrong answer there produces a plausible-looking picture of
 * the wrong thing.
 */
import type { SvgFeature, SvgTrack } from "@soymutdb/genome-view";
import type { RegionGene, RegionTranscript } from "@soymutdb/api-client";

/** A point of interest the window was opened for (an insertion site). */
export interface LocusMarker {
  position: number;
  label: string;
}

/**
 * The transcript that best represents a gene in a small window.
 *
 * `is_canonical` first because the annotation declares it. Otherwise the
 * longest transcript, measured by how many typed segments it has: a partially
 * imported or non-coding record renders as a bare bar under any other rule, and
 * a bar is indistinguishable from "this gene has no structure on record".
 * Ties resolve by the API's own order so the choice is stable across refetches.
 */
export function pickRepresentativeTranscript(
  transcripts: RegionTranscript[],
): RegionTranscript | null {
  if (transcripts.length === 0) return null;
  const canonical = transcripts.filter((transcript) => transcript.is_canonical);
  const pool = canonical.length > 0 ? canonical : transcripts;
  return pool.reduce((best, candidate) =>
    candidate.parts.length > best.parts.length ? candidate : best,
  );
}

/**
 * The accession without its annotation-version suffix, for drawing inside a
 * gene body.
 *
 * `Glyma.01G015400.Wm82.a6.v1` is 29 characters — wider on screen than the
 * 1.6 kb gene it labels at a 20 kb zoom, so five of them in one window paint
 * over each other and the lane becomes unreadable. `Glyma.01G015400` fits.
 * This is only the in-figure label: the page lists every gene with its full
 * accession, and the tooltip carries the coordinates.
 */
export function shortGeneLabel(geneId: string): string {
  const segments = geneId.split(".");
  // Two segments is already the accession (`Glyma.01G000100`, `AT1G01010.1`);
  // more means a version suffix was appended by the annotation pipeline.
  return segments.length > 3 ? segments.slice(0, 2).join(".") : geneId;
}

/**
 * One locus feature per gene: its body plus the representative transcript's
 * CDS and UTR segments.
 *
 * Only one transcript per gene is drawn. Overlaying every isoform's segments
 * would stack several CDS boxes on the same coordinates, and the picture would
 * claim a density of coding sequence that no single transcript has.
 */
export function geneFeature(gene: RegionGene): SvgFeature {
  const transcript = pickRepresentativeTranscript(gene.transcripts);
  return {
    id: gene.gene_id,
    start: gene.start,
    end: gene.end,
    kind: "gene",
    label: shortGeneLabel(gene.gene_id),
    strand: gene.strand === "-" ? "-" : "+",
    // An empty array is meaningful: it says "no structure on record", and the
    // renderer draws the body as a single bar rather than an empty lane.
    parts: (transcript?.parts ?? []).map((part) => ({
      start: part.start,
      end: part.end,
      kind: part.kind,
    })),
  };
}

export interface BuildLocusTracksInput {
  chromosome: string;
  genes: RegionGene[];
  /** Markers drawn as their own lane; omitted when empty. */
  markers?: LocusMarker[];
  /** The window itself, so the view can label its ruler with sizes. */
  spanBp: number;
}

/** Ruler + gene models + markers, in the order a browser stacks them. */
export function buildLocusTracks({
  chromosome,
  genes,
  markers = [],
  spanBp,
}: BuildLocusTracksInput): SvgTrack[] {
  const tracks: SvgTrack[] = [
    { id: "ruler", label: chromosome, kind: "ruler" },
    {
      id: "genes",
      label: `基因 (${genes.length})`,
      kind: "feature",
      features: genes.map(geneFeature),
    },
  ];
  if (markers.length > 0) {
    tracks.push({
      id: "markers",
      label: `标记 (${markers.length})`,
      kind: "feature",
      features: markers.map((marker, index) => ({
        id: `marker-${index}`,
        // A one-base mark is invisible at a 20 kb zoom, so the marker gets a
        // fixed footprint in bases: at least 0.4% of the window.
        start: marker.position,
        end: marker.position + Math.max(1, Math.round(spanBp * 0.004)),
        kind: "mutation" as const,
        label: marker.label,
      })),
    });
  }
  return tracks;
}

/**
 * Window bounds for a centred locus, clamped to the chromosome.
 *
 * `position` is 1-based; a flank that would run off the start of the
 * chromosome clamps to 1 rather than producing a negative coordinate, and the
 * far edge extends by the same amount so the site stays centred when possible.
 */
export function locusWindow(
  position: number,
  flank: number,
  chromosomeLength: number | undefined,
): { start: number; end: number } {
  const safeFlank = Math.max(0, Math.floor(flank));
  const start = Math.max(1, Math.floor(position) - safeFlank);
  const end = Math.max(start + 1, Math.floor(position) + safeFlank);
  if (chromosomeLength && chromosomeLength > 0) {
    return { start, end: Math.min(end, chromosomeLength) };
  }
  return { start, end };
}
