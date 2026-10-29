import type { components } from "./generated/openapi";
import { http } from "./auth";

export interface VariantSummary {
  variant_id: string;
  chromosome: string;
  position: number;
  ref_allele: string;
  alt_allele: string;
  variant_type: string;
  /** Assembly key the row came from; lets an "All assemblies" list label rows. */
  assembly?: string | null;
  consequence?: string;
  impact?: string;
  gene_id?: string;
  gene_symbol?: string;
  hgvs_p?: string;
  hgvs_c?: string;
  quality?: number;
  filter?: string;
  allele_frequency?: number;
}

export interface VariantDetail extends VariantSummary {
  end_position?: number;
  length?: number;
  variant_subtype?: string;
  transcript_id?: string;
  is_canonical_transcript?: boolean;
  location_in_gene?: string;
  exon_number?: number;
  intron_number?: number;
  distance_to_gene?: number;
  protein_position?: number;
  amino_acid_ref?: string;
  amino_acid_alt?: string;
  codon_change?: string;
  /** Public mutant-line identifier; the internal key is never exposed. */
  mutant_line_public_id?: string;
  genotype?: string;
  zygosity?: string;
  read_depth?: number;
  ref_depth?: number;
  alt_depth?: number;
  genotype_quality?: number;
  mutagen?: string;
  is_nonsense?: boolean;
  is_missense?: boolean;
  is_synonymous?: boolean;
  is_frameshift?: boolean;
  is_inframe?: boolean;
  has_splicing_effect?: boolean;
  is_coding?: boolean;
  release_id?: string;
  assembly_id?: string;
  jbrowse_url?: string;
}

export interface VariantSearchResponse {
  items: VariantSummary[];
  cursor: string | null;
  next_cursor: string | null;
  has_more: boolean;
  total_count: number | null;
}

export type VariantType = "SNP" | "INS" | "DEL" | "MNV" | "SV";
export type VariantImpact = "HIGH" | "MODERATE" | "LOW" | "MODIFIER";

/** Public GET /variants filter vocabulary. Keep this aligned with VariantFilterParams in the API. */
export interface VariantFilterParams {
  assembly?: string;
  chromosome?: string;
  start?: number;
  end?: number;
  ref?: string;
  alt?: string;
  gene_id?: string;
  /**
   * Public mutant-line identifier (e.g. `SM7K3ZQ9P2AX`).
   *
   * Sent as `mutant_line_public_id`: the server resolves it to the line's
   * variant facts inside the pinned release. A numeric/internal value is
   * rejected with 422, so never pass a persistence key here.
   */
  mutant_line_public_id?: string;
  variant_type?: VariantType;
  consequence?: string;
  impact?: VariantImpact;
  min_af?: number;
  max_af?: number;
}

export interface VariantSearchParams extends VariantFilterParams {
  cursor?: string;
  limit?: number;
}

export function searchVariants(
  params: VariantSearchParams,
): Promise<VariantSearchResponse> {
  return http.get<VariantSearchResponse>("/variants", { params });
}

export function getVariantDetail(
  variantId: string,
  releaseId?: string,
): Promise<VariantDetail> {
  return http.get<VariantDetail>(`/variants/${variantId}`, {
    params: { release_id: releaseId },
  });
}

export interface RegionVariantParams {
  release_id?: string;
  assembly_id?: string;
  variant_types?: string[];
  impacts?: string[];
  max_results?: number;
}

export function getVariantsByRegion(
  chromosome: string,
  start: number,
  end: number,
  params: RegionVariantParams = {},
): Promise<VariantSummary[]> {
  return http.get<VariantSummary[]>("/variants/region", {
    params: { chromosome, start, end, ...params },
  });
}

/**
 * Query variants in a genomic region by assembly *name*.
 *
 * The backend (GET /variants/region) requires the `assembly` name query
 * parameter (see apps/api/app/api/v1/variants.py); the legacy
 * `getVariantsByRegion` above sends `assembly_id` and is kept untouched.
 */
export interface RegionQueryParams {
  assembly: string;
  chromosome: string;
  start: number;
  end: number;
  max_results?: number;
}

export function searchRegionVariants(
  params: RegionQueryParams,
): Promise<VariantSummary[]> {
  return http.get<VariantSummary[]>("/variants/region", { params });
}

export function createVariantExport(data: unknown): Promise<unknown> {
  return http.post<unknown>("/variants/export", { json: data });
}

/** Lifecycle state of a submitted export (owner or administrator only). */
export type VariantExportStatus = components["schemas"]["ExportStatusResponse"];

/** A short-lived download link for a finished export artifact. */
export type VariantExportDownload = components["schemas"]["ExportDownloadResponse"];

export function getVariantExportStatus(
  exportId: string,
): Promise<VariantExportStatus> {
  return http.get<VariantExportStatus>(`/variants/export/${exportId}`);
}

export function getVariantExportDownload(
  exportId: string,
): Promise<VariantExportDownload> {
  return http.get<VariantExportDownload>(`/variants/export/${exportId}/download`);
}
