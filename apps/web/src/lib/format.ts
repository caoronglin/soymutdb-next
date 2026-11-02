/**
 * Formatting helpers for Web.
 *
 * UI-agnostic formatters are re-exported from @soymutdb/shared/format;
 * genomic-specific helpers stay app-local below.
 */

export {
  formatNumber,
  formatPercent,
  formatFileSize,
  truncate,
  formatDate,
} from "@soymutdb/shared/format";

/** Default species (soybean) has 20 chromosomes — canonical names used across the UI. */
export const SOYBEAN_CHROMOSOMES = Array.from({ length: 20 }, (_, i) => `chr${String(i + 1).padStart(2, "0")}`) as readonly string[];

/** Format a genomic position with thousands separators (e.g. 12,345,678). */
export function formatPosition(pos: number | null | undefined): string {
  if (pos === null || pos === undefined || Number.isNaN(pos)) return "—";
  return new Intl.NumberFormat("en-US").format(pos);
}

/** Build a JBrowse 2 deep link for a genomic location.
 *
 * ``assembly`` should be the JBrowse assembly name (e.g. ``Wm82.a4.v1``).
 * Missing assembly context fails closed with an empty href; callers must not
 * silently select a different genome namespace.
 */
export function jbrowseUrl(
  loc: { chromosome: string; start?: number; end?: number },
  assembly?: string,
): string {
  if (!assembly) return "";
  const assemblyName = assembly;
  const locStr =
    loc.start && loc.end
      ? `${loc.chromosome}:${Math.max(1, loc.start)}..${loc.end}`
      : loc.chromosome;
  const params = new URLSearchParams({
    assembly: assemblyName,
    loc: locStr,
  });
  return `/browser?${params.toString()}`;
}
