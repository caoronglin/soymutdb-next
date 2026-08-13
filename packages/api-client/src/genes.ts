import { http } from "./auth";

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
  cursor: string | null;
  next_cursor: string | null;
  has_more: boolean;
  total_count: number | null;
}

export interface GeneSearchParams {
  q?: string;
  assembly_id?: string;
  chromosome?: string;
  biotype?: string;
  start_pos?: number;
  end_pos?: number;
  cursor?: string;
  limit?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
}

export function searchGenes(params: GeneSearchParams): Promise<GeneSearchResponse> {
  const { q, ...rest } = params;
  return http.get<GeneSearchResponse>("/genes", {
    params: { ...rest, search: q },
  });
}

export function getGene(geneId: string, releaseId?: string): Promise<GeneDetail> {
  return http.get<GeneDetail>(`/genes/${geneId}`, {
    params: { release_id: releaseId },
  });
}

export interface GeneVariantParams {
  release_id?: string;
  impact?: string[];
  variant_type?: string[];
  cursor?: string;
  limit?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
}

/** A genome assembly (GET /genes/assemblies). */
export interface AssemblyInfo {
  id: string | number;
  name: string;
  species: string;
  version: string;
  is_default: boolean;
}

/** List all genome assemblies. */
export function getAssemblies(): Promise<AssemblyInfo[]> {
  return http.get<AssemblyInfo[]>("/genes/assemblies");
}

export interface ChromosomeInfo {
  id: string | number;
  assembly_id: string | number;
  name: string;
  length: number;
  order: number;
}

export function getAssemblyChromosomes(
  assemblyId: string | number,
): Promise<ChromosomeInfo[]> {
  return http.get<ChromosomeInfo[]>(`/genes/assemblies/${assemblyId}/chromosomes`);
}
