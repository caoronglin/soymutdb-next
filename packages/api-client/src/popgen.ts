/**
 * Typed population-genetics tools: LD, nucleotide diversity, allele frequency.
 *
 * All three are public, read-only POST endpoints under `/tools` that aggregate
 * the released `variant_facts` store. They use the pure `request` transport
 * with `auth: false`, matching the other public tools.
 *
 * `r_squared` is the one field that must not be flattened: the store carries
 * per-variant allele frequencies but no per-sample genotype calls, so without
 * an inline genotype matrix the server answers `r_squared: null` plus a `note`.
 * That `null` means "not computable from this store" — never "zero LD" — and
 * callers must render it as such.
 */

import { request, TimeoutPresets } from "./client";

/**
 * Region selector: a gene accession, or an explicit assembly interval.
 *
 * Exactly one mode is allowed; the interval mode requires all four of
 * assembly/chromosome/start/end and is capped at 50 Mb server-side.
 */
export interface PopgenRegionQuery {
  gene_id?: string;
  assembly?: string;
  chromosome?: string;
  start?: number;
  end?: number;
}

/** Sample × variant dosage matrix (0/1/2, no missing calls) for LD. */
export interface GenotypeMatrix {
  sample_ids: string[];
  variant_ids: string[];
  values: number[][];
}

export interface LdRequest extends PopgenRegionQuery {
  /** Inline genotypes; omit it and the server cannot compute r². */
  genotypes?: GenotypeMatrix;
}

export interface LdVariant {
  variant_id: string;
  chromosome: string;
  position: number;
  ref_allele: string;
  alt_allele: string;
}

export interface LdResponse {
  source: string;
  gene_id: string | null;
  assembly: string;
  chromosome: string;
  start: number;
  end: number;
  n_variants: number;
  variants: LdVariant[];
  /**
   * Pairwise r² matrix. `null` means the store has no per-sample genotypes, so
   * r² is *unknown* — not zero and not empty.
   */
  r_squared: number[][] | null;
  note: string | null;
  details: Record<string, unknown> | null;
}

export interface DiversityRequest extends PopgenRegionQuery {
  /** Enables Watterson's θ; θ stays null when the sample size is unknown. */
  sample_size?: number;
  /** Per-window π binning in bp; 0 disables windows. */
  window_size?: number;
}

export interface DiversityWindow {
  start: number;
  end: number;
  n_variants: number;
  segregating_sites: number;
  pi: number;
}

export interface DiversityResponse {
  source: string;
  gene_id: string | null;
  assembly: string;
  chromosome: string;
  start: number;
  end: number;
  n_bp: number;
  n_variants: number;
  segregating_sites: number;
  /** π per base pair; `null` when the region holds no polymorphic site. */
  pi: number | null;
  pi_per_site: number | null;
  /** Watterson's θ (per bp); `null` without a sample size. */
  theta: number | null;
  windows: DiversityWindow[] | null;
}

export interface AlleleFreqRequest extends PopgenRegionQuery {
  max_variants?: number;
}

export interface AlleleFreqVariant {
  variant_id: string;
  chromosome: string;
  position: number;
  ref_allele: string;
  alt_allele: string;
  allele_frequency: number | null;
  variant_type: string;
  gene_id: string | null;
}

export interface AlleleFreqResponse {
  source: string;
  gene_id: string | null;
  assembly: string;
  chromosome: string;
  start: number;
  end: number;
  n_variants: number;
  variants: AlleleFreqVariant[];
}

/** Variant coordinates plus the r² matrix, when genotype data is supplied. */
export function computeLd(query: LdRequest): Promise<LdResponse> {
  return request<LdResponse>("/tools/ld", {
    method: "POST",
    auth: false,
    json: query,
    timeoutMs: TimeoutPresets.CRITICAL,
  });
}

/** Nucleotide diversity (π) and Watterson's θ for a gene or interval. */
export function computeDiversity(
  query: DiversityRequest,
): Promise<DiversityResponse> {
  return request<DiversityResponse>("/tools/diversity", {
    method: "POST",
    auth: false,
    json: query,
    timeoutMs: TimeoutPresets.CRITICAL,
  });
}

/** Per-variant allele frequencies for a gene or interval. */
export function computeAlleleFreq(
  query: AlleleFreqRequest,
): Promise<AlleleFreqResponse> {
  return request<AlleleFreqResponse>("/tools/allelefreq", {
    method: "POST",
    auth: false,
    json: query,
    timeoutMs: TimeoutPresets.CRITICAL,
  });
}
