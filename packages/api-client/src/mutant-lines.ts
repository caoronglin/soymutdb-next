import { http } from "./auth";

export interface MutantLineSummary {
  id: string;
  line_id: string;
  line_name: string;
  mutagen: string;
  ecotype?: string;
  generation?: string;
  description?: string;
  variant_count?: number;
  phenotype_count?: number;
  available_seeds?: number;
  created_at: string;
}

export interface MutantLineDetail extends MutantLineSummary {
  genetic_background?: string;
  parent_line?: string;
  is_active: boolean;
  extra?: Record<string, unknown>;
}

export interface Phenotype {
  id: string;
  trait: string;
  value?: string;
  description?: string;
  condition?: string;
}

export interface SeedInventory {
  id: string;
  line_id: string;
  generation: string;
  quantity_available: number;
  storage_location?: string;
  harvest_date?: string;
}

export interface MutantLineSearchParams {
  q?: string;
  mutagen?: string;
  ecotype?: string;
  generation?: string;
  has_phenotypes?: boolean;
  has_seeds?: boolean;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
}

export interface MutantLineSearchResponse {
  items: MutantLineSummary[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export function searchMutantLines(
  params: MutantLineSearchParams,
): Promise<MutantLineSearchResponse> {
  return http.get<MutantLineSearchResponse>("/mutant-lines", { params });
}

export function getMutantLine(lineId: string): Promise<MutantLineDetail> {
  return http.get<MutantLineDetail>(`/mutant-lines/${lineId}`);
}

export function getMutantLinePhenotypes(lineId: string): Promise<Phenotype[]> {
  return http.get<Phenotype[]>(`/mutant-lines/${lineId}/phenotypes`);
}

export function getMutantLineSeeds(lineId: string): Promise<SeedInventory[]> {
  return http.get<SeedInventory[]>(`/mutant-lines/${lineId}/seeds`);
}

export interface MutantLineVariantParams {
  page?: number;
  page_size?: number;
  variant_type?: string[];
  impact?: string[];
}

export function getMutantLineVariants(
  lineId: string,
  params: MutantLineVariantParams = {},
): Promise<unknown> {
  return http.get<unknown>(`/mutant-lines/${lineId}/variants`, { params });
}

export const MUTAGENS = ["EMS", "T-DNA", "CRISPR", "Fast_Neutron", "Gamma_Ray"] as const;
export const GENERATIONS = ["M0", "M1", "M2", "M3", "M4", "M5", "T0", "T1", "T2", "T3"] as const;
