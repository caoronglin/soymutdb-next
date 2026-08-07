import { http } from "./client";

export interface VariantSummary {
  variant_id: string;
  chromosome: string;
  position: number;
  ref_allele: string;
  alt_allele: string;
  variant_type: string;
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
  mutant_line_id?: string;
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
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface VariantFilterParams {
  chromosome?: string;
  start_pos?: number;
  end_pos?: number;
  gene_id?: string;
  gene_symbol?: string;
  variant_type?: string[];
  impact?: string[];
  consequence?: string[];
  mutant_line_id?: string;
  mutagen?: string;
  zygosity?: string[];
  min_read_depth?: number;
  min_allele_frequency?: number;
  max_allele_frequency?: number;
  min_quality?: number;
  filter_pass_only?: boolean;
  is_nonsense?: boolean;
  is_missense?: boolean;
  is_synonymous?: boolean;
  is_frameshift?: boolean;
  has_splicing_effect?: boolean;
  release_id?: string;
  assembly_id?: string;
}

export interface VariantSearchParams extends VariantFilterParams {
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
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

export function getGeneVariantSummary(
  geneId: string,
  releaseId?: string,
): Promise<unknown> {
  return http.get<unknown>(`/variants/summary/gene/${geneId}`, {
    params: { release_id: releaseId },
  });
}

export function createVariantExport(data: unknown): Promise<unknown> {
  return http.post<unknown>("/variants/export", { json: data });
}

export function getExportStatus(jobId: string): Promise<unknown> {
  return http.get<unknown>(`/variants/export/${jobId}`);
}
