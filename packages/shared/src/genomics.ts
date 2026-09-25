/**
 * Genome-coordinate helpers shared by the portal views.
 *
 * Framework-neutral on purpose: the React and Vue portals (and the
 * page-builder seed) all need the same chromosome vocabulary, the same
 * 1-based inclusive coordinate formatting, and the same JBrowse deep-link
 * shape. Keeping them here is what stops two portals from drifting on
 * what "Chr01:100-200" means.
 */

/** Default species (soybean) has 20 chromosomes — canonical names used across the UI. */
export const SOYBEAN_CHROMOSOMES = Array.from(
  { length: 20 },
  (_, index) => `chr${String(index + 1).padStart(2, "0")}`,
) as readonly string[];

/** Approximate chromosome lengths (bp) for the Wm82.a4.v1 assembly. */
export const CHROMOSOME_LENGTHS_BP: Readonly<Record<string, number>> = {
  chr01: 56_138_617,
  chr02: 51_425_839,
  chr03: 47_790_268,
  chr04: 49_818_099,
  chr05: 42_025_037,
  chr06: 51_425_037,
  chr07: 44_841_275,
  chr08: 47_034_472,
  chr09: 47_045_555,
  chr10: 50_942_514,
  chr11: 39_410_499,
  chr12: 40_445_376,
  chr13: 44_514_122,
  chr14: 50_318_052,
  chr15: 50_366_376,
  chr16: 38_178_317,
  chr17: 42_739_029,
  chr18: 62_465_519,
  chr19: 50_716_349,
  chr20: 47_348_134,
} as const;

/** Format a genomic position with thousands separators (e.g. 12,345,678). */
export function formatPosition(position: number | null | undefined): string {
  if (position === null || position === undefined || Number.isNaN(position)) return "—";
  return new Intl.NumberFormat("en-US").format(position);
}

/** Format a position as a human-readable Mb string (e.g. 12.35 Mb). */
export function formatMb(position: number | null | undefined): string {
  if (position === null || position === undefined || Number.isNaN(position)) return "—";
  return `${(position / 1_000_000).toFixed(2)} Mb`;
}

/** Truncate a gene ID for compact display (e.g. Glyma.01G000100 → Glyma.01G…). */
export function compactGeneId(geneId: string | null | undefined, max = 14): string {
  if (!geneId) return "—";
  if (geneId.length <= max) return geneId;
  return `${geneId.slice(0, max - 1)}…`;
}

/** Parse `chr01:100-200` into its parts; returns null when unparseable. */
export function parseRegion(
  raw: string,
): { chromosome: string; start: number; end: number } | null {
  const match = /^\s*([^\s:]+)\s*:\s*([\d,]+)\s*-\s*([\d,]+)\s*$/.exec(raw);
  if (!match) return null;
  const start = Number(match[2]!.replace(/,/g, ""));
  const end = Number(match[3]!.replace(/,/g, ""));
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 1 || end < start) return null;
  return { chromosome: match[1]!, start, end };
}

/** `chr01:100-200` from explicit parts (1-based, inclusive). */
export function formatRegion(chromosome: string, start?: number, end?: number): string {
  if (start === undefined || end === undefined) return chromosome;
  return `${chromosome}:${formatPosition(start)}-${formatPosition(end)}`;
}

/**
 * Build the portal's own browser deep link (not the raw JBrowse URL).
 *
 * ``assembly`` should be the assembly name (e.g. ``Wm82.a4.v1``). The browser
 * route resolves the canonical JBrowse origin at runtime, so no absolute
 * origin is baked in here (plan §G2.9).
 */
export function jbrowseUrl(
  location: { chromosome: string; start?: number; end?: number },
  assembly?: string,
): string {
  const params = new URLSearchParams();
  if (assembly) params.set("assembly", assembly);
  if (location.start !== undefined && location.end !== undefined) {
    params.set("loc", `${location.chromosome}:${Math.max(1, location.start)}-${location.end}`);
  } else {
    params.set("loc", location.chromosome);
  }
  return `/browser?${params.toString()}`;
}
