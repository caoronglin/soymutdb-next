import { http } from "./auth";

export interface GeneSummary {
  id: string;
  gene_id: string;
  symbol: string | null;
  name: string | null;
  biotype: string;
  assembly_id: string | null;
  assembly_name: string | null;
  chromosome: string;
  start_pos: number;
  end_pos: number;
  strand: string;
  description: string | null;
  variant_count?: number;
  high_impact_variants?: number;
}

export interface GeneExon {
  id: string;
  start: number;
  end: number;
  order: number;
}

/**
 * Transcript view nested in ``GeneDetail.transcripts`` (mirrors the API's
 * ``_transcript_to_response``): coordinates are 1-based inclusive and the
 * ``is_canonical`` flag marks the representative transcript.
 */
export interface GeneTranscript {
  id: string;
  gene_id: string;
  name: string | null;
  biotype: string | null;
  start: number;
  end: number;
  strand: string;
  is_canonical: boolean;
  exons: GeneExon[];
}

export interface GeneDetail extends GeneSummary {
  source: string;
  extra: Record<string, unknown>;
  transcripts: GeneTranscript[];
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
  next_cursor: string | null;
  has_more: boolean;
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
  cursor?: string;
  limit?: number;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
}

export function searchGenes(params: GeneSearchParams): Promise<GeneSearchResponse> {
  const { q, ...rest } = params;
  return http.get<GeneSearchResponse>("/genes", {
    params: { ...rest, search: q },
  });
}

export function getGene(
  geneId: string,
  params?: { release_id?: string; assembly_id?: string },
): Promise<GeneDetail> {
  return http.get<GeneDetail>(`/genes/${geneId}`, {
    params,
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
  assembly_id: string | number,
): Promise<ChromosomeInfo[]> {
  return http.get<ChromosomeInfo[]>(`/genes/assemblies/${assembly_id}/chromosomes`);
}

/**
 * A typed segment of one transcript, in the vocabulary the portals' renderers
 * speak (`packages/genome-view` places `cds` / `utr5` / `utr3` boxes). The
 * database stores `part_type`; the API translates at its boundary so no client
 * has to know the storage spelling.
 */
export interface TranscriptPart {
  kind: "cds" | "utr5" | "utr3";
  start: number;
  end: number;
}

export interface RegionTranscript {
  id: string;
  name: string | null;
  biotype: string;
  start: number;
  end: number;
  strand: string;
  is_canonical: boolean;
  parts: TranscriptPart[];
}

export interface RegionGene {
  gene_id: string;
  name: string | null;
  chromosome: string;
  start: number;
  end: number;
  start_pos: number;
  end_pos: number;
  strand: string;
  biotype: string;
  transcripts: RegionTranscript[];
}

export interface RegionStructure {
  assembly_id: number;
  assembly_name: string;
  assembly_version: string;
  chromosome: string;
  chromosome_length: number;
  start: number;
  end: number;
  genes: RegionGene[];
  truncated: boolean;
}

export interface RegionStructureParams {
  assemblyId: number | string;
  chromosome: string;
  start: number;
  end: number;
  /** Gene bodies only; skips the CDS/UTR segments. */
  includeParts?: boolean;
}

/**
 * Every gene overlapping a window, with its modelled structure.
 *
 * The per-gene `/{gene_id}/genome-view.svg` route answers "show me this gene";
 * this answers "show me this place", which is what a locus link needs.
 */
export function getRegionStructure(params: RegionStructureParams): Promise<RegionStructure> {
  return http.get<RegionStructure>("/genes/region-structure", {
    params: {
      assembly_id: params.assemblyId,
      chromosome: params.chromosome,
      start: params.start,
      end: params.end,
      ...(params.includeParts === false ? { include_parts: false } : {}),
    },
  });
}
