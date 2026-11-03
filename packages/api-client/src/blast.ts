import { http } from "./auth";
import { ApiError, request } from "./client";
import type { AssemblyInfo, GeneDetail } from "./genes";

export type BlastEngine = "ncbi_blast" | "diamond";
export type BlastProgram = "blastn" | "blastp" | "blastx" | "tblastn" | "tblastx";
export type BlastDatabaseType = "nucl" | "prot";

export const BLAST_PROGRAM_COMPATIBILITY: Record<BlastProgram, { query: "nucl" | "prot"; databases: BlastDatabaseType[] }> = {
  blastn: { query: "nucl", databases: ["nucl"] },
  blastp: { query: "prot", databases: ["prot"] },
  blastx: { query: "nucl", databases: ["prot"] },
  tblastn: { query: "prot", databases: ["nucl"] },
  tblastx: { query: "nucl", databases: ["nucl"] },
};

/** Early alphabet feedback only; record structure and biological limits are API-owned. */
export function hasCompatibleBlastQueryAlphabet(sequence: string, program: BlastProgram): boolean {
  const body = sequence.split(/\r?\n/).filter((line) => !line.trimStart().startsWith(">")).join("").replace(/\s/g, "");
  return BLAST_PROGRAM_COMPATIBILITY[program].query === "nucl"
    ? /^[ACGTNRYSWKMBDHVU]+$/i.test(body)
    : /^[ACDEFGHIKLMNPQRSTVWYBZX*-]+$/i.test(body);
}

export interface BlastDatabase {
  id: string | number;
  name: string;
  db_type: BlastDatabaseType;
  assembly_id: string | number;
  assembly_name?: string | null;
  assembly_version?: string | null;
  assembly_is_default?: boolean | null;
  release_id?: number | null;
  is_active: boolean;
  /** Additive catalog metadata; older deployments may omit these fields. */
  engine?: BlastEngine;
  sequence_type?: "genome" | "cds" | "transcript" | "protein" | "repeat_masked" | "pan_genome" | "family_consensus" | "custom" | null;
  annotation_version?: string | null;
  source_url?: string | null;
  sequence_count?: number | null;
  total_length?: number | null;
  fasta_sha256?: string | null;
  index_version?: string | null;
  build_status?: "pending" | "ready" | "building" | "failed";
  /** Database default within assembly, engine and database type. */
  is_default?: boolean;
  license?: string | null;
}

export interface BlastJob {
  id: string;
  name?: string;
  program: BlastProgram;
  engine?: BlastEngine;
  database: string;
  release_id?: number | null;
  assembly_name?: string | null;
  status: "pending" | "running" | "completed" | "failed" | "cancelled" | "expired";
  query_sequence: string | null;
  parameters: Record<string, unknown>;
  hit_count: number;
  submitted_at: string;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
  error_message?: string;
}

export interface BlastHit {
  hsp_num: number;
  subject_id: string;
  subject_title: string;
  percent_identity: number;
  alignment_length: number;
  mismatches: number;
  gap_opens: number;
  query_start: number;
  query_end: number;
  subject_start: number;
  subject_end: number;
  evalue: number;
  bit_score: number;
  query_id?: string | null;
}

export interface BlastJobParams {
  program: BlastProgram;
  engine?: BlastEngine;
  database: string;
  sequence: string;
  name?: string;
  e_value?: number;
  max_hits?: number;
  word_size?: number;
  identity_cutoff?: number;
}

export interface BlastJobListResponse {
  items: BlastJob[];
  total: number;
  page: number;
  page_size: number;
}

export interface BlastHitListResponse {
  items: BlastHit[];
  total: number;
  download_url?: string | null;
}

export interface PublicBlastSubmitResponse {
  job: BlastJob;
  access_token: string;
  expires_at: string;
}

export interface PublicBlastResultResponse extends BlastHitListResponse {
  job_id: string;
  status: BlastJob["status"];
  error_message?: string | null;
}

export function compatibleBlastDatabases(databases: BlastDatabase[], engine: BlastEngine, program: BlastProgram): BlastDatabase[] {
  if (engine === "diamond" && program !== "blastp") return [];
  const allowed = new Set(BLAST_PROGRAM_COMPATIBILITY[program].databases);
  return databases.filter((database) => database.is_active && database.build_status === "ready" && database.engine === engine && allowed.has(database.db_type));
}

export function getBlastDatabases(): Promise<BlastDatabase[]> {
  return http.get<BlastDatabase[]>("/blast/databases");
}

/** Public database discovery never participates in auth refresh or logout. */
export function getPublicBlastDatabases(): Promise<BlastDatabase[]> {
  return request<BlastDatabase[]>("/blast/databases", { auth: false, cache: "no-store", credentials: "omit" });
}

function publicHeaders(accessToken: string): HeadersInit {
  return { "X-Blast-Token": accessToken };
}

export type PublicBlastJobParams = Omit<BlastJobParams, "program"> & { program: BlastProgram; engine?: BlastEngine };

export function submitPublicBlastJob(params: PublicBlastJobParams): Promise<PublicBlastSubmitResponse> {
  if (params.engine === "diamond" && params.program !== "blastp") throw new Error("DIAMOND supports blastp only");
  return request<{ job: BlastJobApi; access_token: string; expires_at: string }>("/blast/public/jobs", {
    method: "POST",
    auth: false,
    cache: "no-store",
    credentials: "omit",
    json: {
      program: params.program,
      engine: params.engine ?? "ncbi_blast",
      database: params.database,
      query_sequence: params.sequence,
      parameters: {
        evalue: params.e_value,
        max_target_seqs: params.max_hits,
      },
    },
  }).then((response) => ({ ...response, job: normalizeJob(response.job) }));
}

export function getPublicBlastJob(jobId: string, accessToken: string): Promise<BlastJob> {
  return request<BlastJobApi>(`/blast/public/jobs/${encodeURIComponent(jobId)}`, {
    auth: false,
    cache: "no-store",
    credentials: "omit",
    headers: publicHeaders(accessToken),
  }).then(normalizeJob);
}

export function getPublicBlastResults(
  jobId: string,
  accessToken: string,
  params: { limit?: number; offset?: number } = {},
): Promise<PublicBlastResultResponse> {
  return request<PublicBlastResultApi>(`/blast/public/jobs/${encodeURIComponent(jobId)}/results`, {
    auth: false,
    cache: "no-store",
    credentials: "omit",
    headers: publicHeaders(accessToken),
    params,
  }).then((response) => ({
    ...response,
    items: response.hits ?? [],
    total: response.total_hits ?? 0,
    download_url: response.download_url,
  }));
}

export function submitBlastJob(params: BlastJobParams): Promise<BlastJob> {
  return http.post<BlastJobApi>("/blast/jobs", {
    json: {
      program: params.program,
      engine: params.engine ?? "ncbi_blast",
      database: params.database,
      query_sequence: params.sequence,
      parameters: {
        evalue: params.e_value,
        max_target_seqs: params.max_hits,
        word_size: params.word_size,
        percent_identity: params.identity_cutoff,
      },
    },
  }).then(normalizeJob);
}

export function getBlastJobs(params: {
  page?: number;
  page_size?: number;
  status?: string;
} = {}): Promise<BlastJobListResponse> {
  return http.get<BlastJobListResponse & { items: BlastJobApi[] }>("/blast/jobs", { params }).then(
    (response) => ({ ...response, items: response.items.map(normalizeJob) }),
  );
}

export function getBlastJob(jobId: string): Promise<BlastJob> {
  return http.get<BlastJobApi>(`/blast/jobs/${jobId}`).then(normalizeJob);
}

export function getBlastHits(
  jobId: string,
  params: {
    limit?: number;
    offset?: number;
  } = {},
): Promise<BlastHitListResponse> {
  return http.get<BlastResultApi>(`/blast/jobs/${jobId}/results`, {
    params,
  }).then((response) => ({
    items: response.hits ?? [],
    total: response.total_hits ?? 0,
    download_url: response.download_url,
  }));
}

/** A genomic interval proven by a gene record in the searched release/assembly. */
export interface BlastGenomeTarget {
  release: string;
  assembly: string;
  locus: string;
}

/**
 * Resolve lazily on user action, never from DIAMOND subject_start/end (AA).
 * Protein FASTA IDs need not be gene accessions: exact lookup only, no suffix
 * stripping or fuzzy mapping. A missing/ambiguous mapping has no browser target.
 */
export async function resolveBlastHitGenomeTarget(
  job: Pick<BlastJob, "release_id" | "assembly_name">,
  subjectId: string,
): Promise<BlastGenomeTarget | null> {
  const releaseId = job.release_id;
  const assemblyName = job.assembly_name?.trim();
  if (!Number.isSafeInteger(releaseId) || releaseId == null || releaseId < 1
      || !assemblyName || !subjectId.trim()) return null;
  // Explicit request headers override the portal's current global release pin.
  const headers = { "X-SoyMutDB-Release": String(releaseId) };
  const assemblies = await http.get<AssemblyInfo[]>("/genes/assemblies", { headers });
  const matches = assemblies.filter((item) => item.name === assemblyName);
  if (matches.length !== 1) return null;
  const assemblyId = Number(matches[0].id);
  if (!Number.isSafeInteger(assemblyId) || assemblyId < 1) return null;
  let gene: GeneDetail;
  try {
    gene = await http.get<GeneDetail>(`/genes/${encodeURIComponent(subjectId)}`, {
      params: { assembly_id: assemblyId }, headers,
    });
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.code === "ambiguous_assembly")) return null;
    throw error;
  }
  if (String(gene.assembly_id) !== String(assemblyId)
      || gene.gene_id !== subjectId || !gene.chromosome?.trim()
      || !Number.isSafeInteger(gene.start_pos) || !Number.isSafeInteger(gene.end_pos)
      || gene.start_pos < 1 || gene.end_pos < gene.start_pos) return null;
  return {
    release: String(releaseId), assembly: assemblyName,
    locus: `${gene.chromosome}:${gene.start_pos}-${gene.end_pos}`,
  };
}

interface BlastJobApi extends Omit<BlastJob, "id" | "database"> {
  job_id: string;
  database?: string | null;
  database_id: string | number;
}

interface BlastResultApi {
  hits: BlastHit[] | null;
  total_hits: number | null;
  download_url?: string | null;
}

type PublicBlastResultApi = BlastResultApi & {
  job_id: string;
  status: BlastJob["status"];
  error_message?: string | null;
};

function normalizeJob(job: BlastJobApi | BlastJob): BlastJob {
  if ("id" in job) return job;
  return {
    ...job,
    id: job.job_id,
    database: job.database ?? String(job.database_id),
  };
}

/** Program choices; the engine and database catalog further constrain compatibility. */
export const BLAST_PROGRAMS = [
  { id: "blastn", label: "BLASTN", type: "nucleotide", queryType: "nucl", description: "Nucleotide vs nucleotide" },
  { id: "blastp", label: "BLASTP", type: "protein", queryType: "prot", description: "Protein vs protein" },
  { id: "blastx", label: "BLASTX", type: "nucleotide", queryType: "nucl", description: "Translated nucleotide vs protein" },
  { id: "tblastn", label: "TBLASTN", type: "protein", queryType: "prot", description: "Protein vs translated nucleotide" },
  { id: "tblastx", label: "TBLASTX", type: "nucleotide", queryType: "nucl", description: "Translated nucleotide vs translated nucleotide" },
] as const;
