import { http } from "./client";

export interface GeneSummary {
  id: string;
  gene_id: string;
  symbol: string | null;
  name: string | null;
  biotype: string;
  chromosome: string;
  start_pos: number;
  end_pos: number;
  strand: string;
  description: string | null;
  variant_count?: number;
  high_impact_variants?: number;
}

export interface GeneDetail extends GeneSummary {
  source: string;
  extra: Record<string, unknown>;
  transcripts: unknown[];
  annotations: unknown[];
  snp_count?: number;
  indel_count?: number;
  sv_count?: number;
  nonsense_count?: number;
  missense_count?: number;
  synonymous_count?: number;
  frameshift_count?: number;
  mutant_line_count?: number;
}

export interface GeneSearchResponse {
  items: GeneSummary[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface GeneSearchParams {
  q?: string;
  assembly_id?: string;
  chromosome?: string;
  biotype?: string;
  start_pos?: number;
  end_pos?: number;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
}

export function searchGenes(params: GeneSearchParams): Promise<GeneSearchResponse> {
  return http.get<GeneSearchResponse>("/genes", { params });
}

export function getGene(geneId: string, releaseId?: string): Promise<GeneDetail> {
  return http.get<GeneDetail>(`/genes/${geneId}`, {
    params: { release_id: releaseId },
  });
}

export function getGeneTranscripts(geneId: string): Promise<unknown[]> {
  return http.get<unknown[]>(`/genes/${geneId}/transcripts`);
}

export interface GeneVariantParams {
  release_id?: string;
  impact?: string[];
  variant_type?: string[];
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
}

export function getGeneVariants(
  geneId: string,
  params: GeneVariantParams = {},
): Promise<unknown> {
  return http.get<unknown>(`/genes/${geneId}/variants`, { params });
}

export function getGeneAnnotations(
  geneId: string,
  annotationType?: string,
): Promise<unknown[]> {
  return http.get<unknown[]>(`/genes/${geneId}/annotations`, {
    params: { annotation_type: annotationType },
  });
}
