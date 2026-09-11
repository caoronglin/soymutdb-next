import { http } from "./auth";

/** Canonical public identifier for a mutant line (e.g. SM7K3ZQ9P2A). */
export type MutantLineId = string;

export function isMutantLineId(value: string): value is MutantLineId {
  // Canonical ids contain no surrounding whitespace: the guard validates the
  // raw value (URL/path params) so callers never send non-canonical forms.
  // Case is accepted freely; the server uppercases via Crockford mapping.
  return value.length >= 3 && value.length <= 32 && /^[A-Za-z0-9_-]+$/.test(value);
}

/**
 * Compact mutant-line representation returned by GET /mutants.
 */
export interface MutantLineResponse {
  public_id: string;
  name: string;
  mutagen: string | null;
  cultivar: string | null;
  variant_count: number;
}

/**
 * Detailed mutant-line representation returned by GET /mutants/{public_id}.
 */
export interface MutantLineDetail extends MutantLineResponse {
  species: string;
  description: string | null;
  generation: string | null;
  phenotype_summary: string | null;
  is_public: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Phenotype observation returned by GET /mutants/{public_id}/phenotypes.
 */
export interface PhenotypeResponse {
  id: string;
  mutant_line_public_id: string;
  trait_category: string;
  trait_name: string;
  trait_value: string | null;
  unit: string | null;
  description: string | null;
}

/** Query parameters accepted by GET /mutants. */
export interface ListMutantLinesParams {
  mutagen?: string;
  limit?: number;
}

/** List public mutant lines. */
export function listMutantLines(
  params: ListMutantLinesParams = {},
): Promise<MutantLineResponse[]> {
  return http.get<MutantLineResponse[]>("/mutants", { params });
}

/** Get a public mutant line by its public identifier. */
export function getMutantLine(publicId: string): Promise<MutantLineDetail> {
  return http.get<MutantLineDetail>(`/mutants/${publicId}`);
}

/** List phenotype observations for a public mutant line. */
export function getMutantLinePhenotypes(
  publicId: string,
): Promise<PhenotypeResponse[]> {
  return http.get<PhenotypeResponse[]>(`/mutants/${publicId}/phenotypes`);
}
