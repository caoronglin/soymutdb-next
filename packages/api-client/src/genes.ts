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

/**
 * Why a section has nothing to show. ``unavailable`` means the platform holds
 * no such data — it is not an empty result, and the UI must not render it as a
 * zero.
 */
export type SequenceAvailabilityState = "available" | "unavailable";

/**
 * Per-molecule availability for a gene's sequences.
 *
 * The API answers this for genomic/CDS/transcript/protein even when no residue
 * store exists, so the page can say "not imported" instead of rendering a
 * fabricated string. ``sequence`` is only ever populated when
 * ``availability`` is ``"available"``.
 */
export interface GeneSequenceAvailability {
  molecule: "genomic" | "cds" | "transcript" | "protein";
  availability: SequenceAvailabilityState;
  reason: string | null;
  length: number | null;
  checksum: string | null;
  sequence: string | null;
}

/** Evidence strength, strongest first. Never raise one to another. */
export type EvidenceKind =
  | "experimental"
  | "curated"
  | "predicted"
  | "transferred"
  | "imported"
  | "unknown";

/** Provenance of one displayed assertion. */
export interface EvidenceTag {
  kind: EvidenceKind;
  source: string;
}

/**
 * How much a section has to show.
 *
 * ``not_imported`` is not an empty result: the release holds no snapshot for
 * this data at all. ``count`` is ``null`` in that case — never ``0`` — so a
 * caller cannot mistake "unknown" for "measured zero".
 */
export type GeneSectionState = "available" | "empty" | "not_imported";

export type GeneSectionName =
  | "annotation"
  | "homolog"
  | "expression"
  | "variants"
  | "phenotype"
  | "literature";

/** Presence, provenance and evidence of one gene-detail section. */
export interface GeneSectionStatus {
  section: GeneSectionName;
  state: GeneSectionState;
  count: number | null;
  evidence: EvidenceTag | null;
  reason: string | null;
}

/** One GO/KEGG assertion, keeping the source's evidence code. */
export interface GeneAnnotationTerm {
  ontology: "go" | "kegg";
  term_id: string;
  term_name: string;
  /** The source's code verbatim (``IDA``, ``IEA``...); ``null`` if absent. */
  evidence_code: string | null;
  kind: EvidenceKind;
  reference: string | null;
  qualifier: string | null;
}

export interface GeneAnnotationSection {
  status: GeneSectionStatus;
  terms: GeneAnnotationTerm[];
  source_name: string | null;
  source_version: string | null;
  source_url: string | null;
}

export interface GeneHomologRecord {
  homolog_species: string;
  homolog_gene_id: string;
  homolog_type: "ortholog" | "paralog";
  /** How the relation was established; ``null`` when the source is silent. */
  method: string | null;
  source: string | null;
  /** Always ``transferred``: the row describes another locus. */
  kind: EvidenceKind;
  confidence: number | null;
}

export interface GeneHomologSection {
  status: GeneSectionStatus;
  records: GeneHomologRecord[];
}

export interface GeneExpressionRecord {
  library_id: string;
  library_name: string;
  tissue: string | null;
  treatment: string | null;
  stage: string | null;
  /** Units are independently optional; ``null`` means not measured. */
  tpm: number | null;
  fpkm: number | null;
  raw_count: number | null;
}

export interface GeneExpressionSection {
  status: GeneSectionStatus;
  records: GeneExpressionRecord[];
}

export interface GeneVariantSection {
  status: GeneSectionStatus;
  total: number | null;
  by_impact: Record<string, number>;
}

export interface GenePhenotypeRecord {
  mutant_public_id: string;
  mutant_name: string;
  trait_category: string;
  trait_name: string;
  trait_value: string | null;
  unit: string | null;
  measurement_method: string | null;
}

export interface GenePhenotypeSection {
  status: GeneSectionStatus;
  records: GenePhenotypeRecord[];
}

export interface GeneLiteratureRecord {
  title: string;
  authors: string | null;
  journal: string | null;
  year: number | null;
  doi: string | null;
  pmid: string | null;
}

export interface GeneLiteratureSection {
  status: GeneSectionStatus;
  records: GeneLiteratureRecord[];
}

export interface GeneDetail extends GeneSummary {
  source: string;
  extra: Record<string, unknown>;
  transcripts: GeneTranscript[];
  annotations: unknown[];
  /**
   * One entry per molecule. Optional (not `undefined`-by-default on the wire
   * since the schema carries `default_factory`, not `default`), so a client must
   * treat "absent" as "nothing reported", never as "no sequences".
   */
  sequences?: GeneSequenceAvailability[];
  /** How the gene model came to exist; ``null`` when the source is silent. */
  model_evidence?: EvidenceTag | null;
  /**
   * Optional blocks. Each carries its own status, so "this gene has none" and
   * "this release never imported them" stay distinguishable. Optional on the
   * wire: an older API build omits them rather than sending empty lists.
   */
  annotation_section?: GeneAnnotationSection | null;
  homolog_section?: GeneHomologSection | null;
  expression_section?: GeneExpressionSection | null;
  variants_section?: GeneVariantSection | null;
  phenotype_section?: GenePhenotypeSection | null;
  literature_section?: GeneLiteratureSection | null;
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
