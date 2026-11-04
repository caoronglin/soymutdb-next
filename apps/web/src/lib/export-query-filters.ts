/**
 * Filter vocabulary of the export query builder.
 *
 * The backend derives its whitelist from the export-filter schema; this file
 * is the display mirror of that same set. It exists so the card can say what
 * it can query without an extra request. `export-query-filters.test.ts` pins
 * it against the generated client contract, so the mirror cannot silently
 * drift back into advertising a filter the API would refuse.
 */

/** Filters the export pipeline applies — one per `VariantExportFilters` field. */
export const SUPPORTED_EXPORT_QUERY_FILTERS = [
  "assembly", "chromosome", "start", "end", "ref", "alt", "gene_id",
  "variant_type", "consequence", "impact", "min_af", "max_af",
  "mutant_line_public_id",
] as const;

export type SupportedExportQueryFilter =
  (typeof SUPPORTED_EXPORT_QUERY_FILTERS)[number];

/** brief §7 filters with no backing query capability yet — refused by the API. */
export const EXPORT_QUERY_UNSUPPORTED_LABELS = [
  "gene_list", "species", "biotype", "go_term", "kegg_term",
  "expression_threshold", "homolog_species",
] as const;
