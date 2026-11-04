/**
 * Comparative genomics: families, membership, orthologs and derived artifacts.
 *
 * Two properties of this contract are load-bearing and must not be "simplified"
 * by a caller:
 *
 * - `SpeciesCoverage.state === "no_data"` with `member_count: null` means the
 *   source has no row for that species. It is not a measured zero, and it must
 *   not be rendered as one.
 * - nothing here carries an alignment score or identity percentage. A BLAST hit
 *   is a similarity measurement; orthology is a separate, stated claim.
 */
import { http } from "./auth";

/** Membership relationship vocabulary. Never free text. */
export type RelationshipType = "one_to_one" | "one_to_many" | "many_to_many";

/** Presence of comparative data for a scope. */
export type ComparativeState = "available" | "no_data" | "not_imported";

/**
 * Evidence class of a comparative assertion.
 *
 * Mirrors the gene-center vocabulary; `transferred` is the only class a
 * homolog row can carry, because it describes another locus.
 */
export type ComparativeEvidenceKind =
  | "experimental"
  | "curated"
  | "predicted"
  | "transferred"
  | "imported"
  | "unknown";

export interface ComparativeEvidence {
  kind: ComparativeEvidenceKind;
  source: string;
}

export interface FamilyMember {
  gene_accession: string;
  species: string;
  relationship_type: RelationshipType;
  method: string | null;
  confidence: number | null;
  evidence: Record<string, unknown> | null;
}

export interface SpeciesCoverage {
  species: string;
  state: ComparativeState;
  /** `null` when the species contributed no member — never `0`. */
  member_count: number | null;
}

export interface GeneFamily {
  family_id: number;
  level: "gene_family" | "gene_subfamily";
  external_id: string;
  name: string;
  method: string;
  method_version: string | null;
  source_name: string;
  source_version: string;
  source_url: string;
  release_id: number;
  assembly_id: number;
  member_count: number;
  evidence: ComparativeEvidence;
}

export interface GeneFamilyDetail extends GeneFamily {
  members: FamilyMember[];
  coverage: SpeciesCoverage[];
  relationship_types: string[];
}

export interface GeneFamilyList {
  items: GeneFamily[];
  total: number;
  page: number;
  page_size: number;
}

export interface FamilyComparison {
  left: GeneFamily;
  right: GeneFamily;
  shared: FamilyMember[];
  only_left: FamilyMember[];
  only_right: FamilyMember[];
  coverage: SpeciesCoverage[];
}

export interface OrthologRecord {
  gene_accession: string;
  counterpart_species: string | null;
  counterpart_gene_id: string;
  homolog_type: "ortholog" | "paralog";
  relationship_type: RelationshipType;
  method: string | null;
  source: string | null;
  release_id: number | null;
  confidence: number | null;
  evidence: ComparativeEvidence;
}

export interface GeneOrthologs {
  gene_id: string;
  assembly_id: number;
  release_id: number;
  state: ComparativeState;
  records: OrthologRecord[];
}

export type ArtifactKind = "msa" | "tree";
export type ArtifactState = "pending" | "running" | "succeeded" | "failed";

export interface ComparativeArtifact {
  artifact_type: ArtifactKind;
  job_id: string;
  state: ArtifactState;
  method: string;
  /** Hash over the ordered member set this artifact was computed from. */
  input_sha256: string;
  input_member_ids: string[];
  download_url: string | null;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface ComparativeArtifactRequest {
  family_id: number;
  artifact_type: ArtifactKind;
  method: string;
  assembly_id?: number | null;
}

export interface FamilyQuery {
  assembly_id?: number | null;
  level?: "gene_family" | "gene_subfamily";
  page?: number;
  page_size?: number;
}

export function listFamilies(params: FamilyQuery = {}): Promise<GeneFamilyList> {
  return http.get<GeneFamilyList>("/comparative/families", {
    params: {
      assembly_id: params.assembly_id ?? undefined,
      level: params.level,
      page: params.page,
      page_size: params.page_size,
    },
  });
}

export function getFamily(
  familyId: number,
  params: { assembly_id?: number | null } = {},
): Promise<GeneFamilyDetail> {
  return http.get<GeneFamilyDetail>(`/comparative/families/${familyId}`, {
    params: { assembly_id: params.assembly_id ?? undefined },
  });
}

export function compareFamilies(
  left: number,
  right: number,
  params: { assembly_id?: number | null } = {},
): Promise<FamilyComparison> {
  return http.get<FamilyComparison>("/comparative/families/compare", {
    params: { left, right, assembly_id: params.assembly_id ?? undefined },
  });
}

export function getGeneOrthologs(
  geneId: string,
  params: { assembly_id?: number | null; homolog_type?: "ortholog" | "paralog" } = {},
): Promise<GeneOrthologs> {
  return http.get<GeneOrthologs>(`/comparative/genes/${geneId}/orthologs`, {
    params: {
      assembly_id: params.assembly_id ?? undefined,
      homolog_type: params.homolog_type,
    },
  });
}

export function requestArtifact(
  request: ComparativeArtifactRequest,
): Promise<ComparativeArtifact> {
  return http.post<ComparativeArtifact>("/comparative/artifacts", { json: request });
}

export function getArtifact(jobId: string): Promise<ComparativeArtifact> {
  return http.get<ComparativeArtifact>(`/comparative/artifacts/${jobId}`);
}
