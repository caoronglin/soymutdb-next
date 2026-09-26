/**
 * Locus-box resolution for the standalone browser.
 *
 * Coordinate strings resolve locally (1-based inclusive, matching the deep-link
 * contract); every other input is treated as a gene identifier and resolved
 * through an injected `lookupGene`, so the caller picks between the API and a
 * local Trix index without this module knowing either.
 */
// Explicit .ts extension: Node's test runner loads this module directly.
import { parseLocus, type ParsedLocus } from "./deep-link.ts";

/** A gene hit with the coordinates the API returns (1-based inclusive). */
export interface GeneSearchHit {
  readonly gene_id?: string;
  readonly chromosome: string;
  readonly start_pos: number;
  readonly end_pos: number;
}

export interface GeneCoordinate extends ParsedLocus {
  readonly geneId?: string;
}

export type LocusResolution =
  | { readonly kind: "coordinate"; readonly locus: ParsedLocus }
  | { readonly kind: "gene"; readonly gene: GeneCoordinate }
  | { readonly kind: "not-found"; readonly query: string }
  | { readonly kind: "error"; readonly query: string; readonly message: string };

export interface ResolveLocusOptions {
  /** Resolve a gene identifier to coordinates, or null when nothing matches. */
  lookupGene(query: string): Promise<GeneSearchHit | null>;
}

/**
 * Resolve raw locus-box input. Never rejects: a lookup failure becomes an
 * explicit `error` result so the host can show a clear message instead of
 * silently doing nothing.
 */
export async function resolveLocusInput(
  input: string,
  options: ResolveLocusOptions,
): Promise<LocusResolution> {
  const trimmed = input.trim();
  if (!trimmed) return { kind: "not-found", query: input };

  const parsed = parseLocus(trimmed);
  if (parsed) return { kind: "coordinate", locus: parsed };

  try {
    const hit = await options.lookupGene(trimmed);
    if (!hit) return { kind: "not-found", query: trimmed };
    return {
      kind: "gene",
      gene: {
        refName: hit.chromosome,
        start: hit.start_pos,
        end: hit.end_pos,
        ...(hit.gene_id === undefined ? {} : { geneId: hit.gene_id }),
      },
    };
  } catch (error) {
    return {
      kind: "error",
      query: trimmed,
      message: error instanceof Error ? error.message : String(error),
    };
  }
}

const TRIX_LOCATION = /([A-Za-z0-9_.]+):([\d,]+)(?:\.\.|-)([\d,]+)/;

/**
 * Decode the location from a Trix record payload. Trix substitutes "|" for
 * commas, so normalise first, then read the first location-like token.
 * Returns 1-based inclusive coordinates.
 */
export function parseTextSearchLabel(label: string): ParsedLocus | null {
  const match = label.replace(/\|/g, ",").match(TRIX_LOCATION);
  if (!match) return null;
  const start = Number.parseInt(match[2].replace(/,/g, ""), 10);
  const end = Number.parseInt(match[3].replace(/,/g, ""), 10);
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return { refName: match[1], start, end };
}
