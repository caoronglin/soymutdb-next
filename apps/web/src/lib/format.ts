/**
 * Shared formatting helpers for genomic data display.
 */

/** Format a numeric value with thousands separators; "—" for null/NaN. */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat().format(value);
}

/** Format a value as a percentage with the given decimals; "—" for null/NaN. */
export function formatPercent(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(decimals)}%`;
}

/** Format a byte count as a human-readable size (B/KB/MB/GB/TB); "—" for null. */
export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** unit).toFixed(1)} ${units[unit]}`;
}

/** Truncate a string with an ellipsis when it exceeds maxLength. */
export function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 1))}…`;
}

/** Default species (soybean) has 20 chromosomes — canonical names used across the UI. */
export const SOYBEAN_CHROMOSOMES = Array.from({ length: 20 }, (_, i) => `chr${String(i + 1).padStart(2, "0")}`) as readonly string[];

/** Approximate chromosome lengths (bp) for the Wm82.a4.v1 assembly. Used for hero visualization. */
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
export function formatPosition(pos: number | null | undefined): string {
  if (pos === null || pos === undefined || Number.isNaN(pos)) return "—";
  return new Intl.NumberFormat("en-US").format(pos);
}

/** Format a position as a human-readable Mb string (e.g. 12.35 Mb). */
export function formatMb(pos: number | null | undefined): string {
  if (pos === null || pos === undefined || Number.isNaN(pos)) return "—";
  return `${(pos / 1_000_000).toFixed(2)} Mb`;
}

/** Build a JBrowse 2 deep link for a genomic location. */
export function jbrowseUrl(loc: { chromosome: string; start?: number; end?: number }): string {
  const assembly = "Wm82.a4.v1";
  const locStr =
    loc.start && loc.end
      ? `${loc.chromosome}:${Math.max(1, loc.start)}..${loc.end}`
      : loc.chromosome;
  const params = new URLSearchParams({
    assembly,
    loc: locStr,
  });
  return `/browser?${params.toString()}`;
}

/** Convert an ISO date string to a localized short date. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric" }).format(d);
}

/** Truncate a gene ID for compact display (e.g. Glyma.01G000100 → Glyma.01G…). */
export function compactGeneId(geneId: string | null | undefined, max = 14): string {
  if (!geneId) return "—";
  if (geneId.length <= max) return geneId;
  return `${geneId.slice(0, max - 1)}…`;
}
