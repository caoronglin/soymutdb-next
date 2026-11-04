/** Filter vocabulary mirrored from the backend whitelist (display only). */

export const SUPPORTED_EXPORT_QUERY_FILTERS = [
  "assembly", "chromosome", "start", "end", "ref", "alt", "gene_id",
  "variant_type", "consequence", "impact", "min_af", "max_af",
  "mutant_line_public_id",
] as const;

/** brief §7 filters with no backing query capability yet — refused by the API. */
export const EXPORT_QUERY_UNSUPPORTED_LABELS = [
  "gene_list", "species", "biotype", "go_term", "kegg_term",
  "expression_threshold", "homolog_species",
] as const;
