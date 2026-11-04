import { http } from "./auth";
import { ApiError, request } from "./client";

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
    // `-` last in the class: a literal hyphen needs no escape there, and an
    // escaped one trips no-useless-escape under this ESLint version.
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
  /** Mirrors the backend catalog state machine (see openapi.d.ts). */
  build_status?: "pending" | "building" | "validating" | "publishing" | "published" | "failed" | "ready";
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
  /** Assembly-scoped genomic locus, only when a protein/transcript subject was
   * resolved through an explicit relation. Never derived from AA coordinates. */
  genome_resolution?: BlastGenomeResolution | null;
}

/** Proven genomic interval or an explicit "unresolved" reason. */
export interface BlastGenomeResolution {
  status: "resolved" | "unresolved";
  reason?: string;
  gene_id?: string;
  chromosome?: string;
  start?: number;
  end?: number;
  strand?: string;
  assembly_id?: number;
  release_id?: number;
  relation?: string;
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
  return databases.filter((database) => database.is_active
    && (database.build_status === "published" || database.build_status === "ready")
    && database.engine === engine && allowed.has(database.db_type));
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

/** Public result reads are always no-store: download URLs are short-lived. */
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
  /** Explicit relation used to resolve the subject; never an inferred coordinate. */
  resolution?: "gene_accession" | "gene_alias" | "transcript_id";
}

interface GenomeTargetApi {
  status: "resolved" | "unresolved";
  reason?: string | null;
  gene_id?: string | null;
  chromosome?: string | null;
  start?: number | null;
  end?: number | null;
  strand?: string | null;
  release_id?: number | null;
  assembly_id?: number | null;
  assembly_name?: string | null;
  locus?: string | null;
  resolution?: BlastGenomeTarget["resolution"];
}

/**
 * Resolve a BLAST subject through the API's explicit gene/alias/transcript
 * relation in the job's own release and assembly. Amino-acid alignment
 * coordinates (blastp/blastx/tblastn subject_start/end) are never sent and
 * never interpreted as genomic positions. An unresolved subject returns
 * `null`; callers must surface that explicitly rather than guessing a locus.
 */
export async function resolveBlastHitGenomeTarget(
  job: Pick<BlastJob, "id" | "release_id" | "assembly_name">,
  subjectId: string,
  options: { publicToken?: string } = {},
): Promise<BlastGenomeTarget | null> {
  const jobId = job.id?.trim();
  const subject = subjectId?.trim();
  if (!jobId || !subject || !Number.isSafeInteger(job.release_id) || job.release_id == null
      || job.release_id < 1 || !job.assembly_name?.trim()) return null;
  const path = options.publicToken
    ? `/blast/public/jobs/${encodeURIComponent(jobId)}/hits/${encodeURIComponent(subject)}/genome-target`
    : `/blast/jobs/${encodeURIComponent(jobId)}/hits/${encodeURIComponent(subject)}/genome-target`;
  const headers: Record<string, string> = options.publicToken
    ? { "X-Blast-Token": options.publicToken } : {};
  let response: GenomeTargetApi;
  try {
    response = options.publicToken
      ? await request<GenomeTargetApi>(path, {
          auth: false, cache: "no-store", credentials: "omit", headers,
        })
      : await http.get<GenomeTargetApi>(path);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.code === "not_found")) return null;
    throw error;
  }
  if (response.status !== "resolved" || !response.locus || !response.assembly_name
      || !Number.isSafeInteger(response.release_id) || response.release_id == null
      || String(response.release_id) !== String(job.release_id)
      || response.assembly_name !== job.assembly_name
      || !Number.isSafeInteger(response.start) || !Number.isSafeInteger(response.end)
      || response.start == null || response.end == null || response.start < 1
      || response.end < response.start) return null;
  return {
    release: String(response.release_id),
    assembly: response.assembly_name,
    locus: response.locus,
    resolution: response.resolution,
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

// ---------------------------------------------------------------------------
// Shared search-form rules (anonymous and signed-in BLAST are the same search)
// ---------------------------------------------------------------------------

/** Submission-critical FASTA problems, ordered by where the reader should look. */
export type FastaStructureError = "emptyRecord";

/**
 * Structural FASTA check for multi-record queries. One BLAST job may carry
 * several records; every record that has a header also needs a sequence.
 * Alphabet is checked separately by
 * `hasCompatibleBlastQueryAlphabet` (early feedback only — the API is the
 * authority for the alphabet, record limits and duplicate identifiers).
 *
 * A header-less query is a pasted bare sequence, not malformed FASTA: the API
 * and the worker both accept it, so no client rule may reject it.
 */
export function validateBlastFastaStructure(sequence: string): FastaStructureError | null {
  const lines = sequence.split(/\r?\n/);
  let sawHeader = false;
  let currentHasSequence = false;
  let sawAny = false;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    sawAny = true;
    if (line.startsWith(">")) {
      if (sawHeader && !currentHasSequence) return "emptyRecord";
      sawHeader = true;
      currentHasSequence = false;
      continue;
    }
    if (!sawHeader) return null; // pasted bare sequence: the API accepts it
    currentHasSequence = true;
  }
  if (!sawAny) return null;
  return currentHasSequence ? null : "emptyRecord";
}

/** Display name of a search engine. Product names, not translatable copy. */
export function blastEngineLabel(
  engine: BlastEngine | undefined,
  unknownEngine: string,
): string {
  if (engine === "ncbi_blast") return "NCBI BLAST+";
  if (engine === "diamond") return "DIAMOND";
  return unknownEngine;
}

/** One browser download for a job's raw aligner output (presigned URL). */
export interface BlastDownloadLink {
  href: string;
  filename: string;
}

/**
 * Build the download link for raw BLAST output.
 *
 * The raw artifact is the engine's tabular text (outfmt 6), so the filename
 * says .tsv instead of inheriting the storage key's .txt suffix. The caller
 * only passes URLs that survived the scheme check in the page components.
 */
export function blastDownloadLink(
  url: string | null | undefined,
  job: { id: string; program: BlastProgram; engine?: BlastEngine },
): BlastDownloadLink | null {
  if (!url) return null;
  const engine = job.engine === "diamond" ? "diamond" : "ncbi_blast";
  return { href: url, filename: `${job.id.slice(0, 8)}-${engine}-${job.program}.tsv` };
}

/** Cancel a pending/running job. Both engines share the same lifecycle. */
export function cancelBlastJob(jobId: string): Promise<BlastJob> {
  return http.post<BlastJobApi>(`/blast/jobs/${encodeURIComponent(jobId)}/cancel`).then(normalizeJob);
}

export function cancelPublicBlastJob(jobId: string, accessToken: string): Promise<BlastJob> {
  return request<BlastJobApi>(`/blast/public/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST", auth: false, cache: "no-store", credentials: "omit",
    headers: publicHeaders(accessToken),
  }).then(normalizeJob);
}

/** Retry a failed/expired job as a new job; results are never overwritten. */
export function retryBlastJob(jobId: string): Promise<BlastJob> {
  return http.post<BlastJobApi>(`/blast/jobs/${encodeURIComponent(jobId)}/retry`).then(normalizeJob);
}

export type BlastIndexBuildState =
  | "pending" | "building" | "validating" | "publishing" | "published" | "failed" | "ready";

export interface BlastIndexBuild {
  build_id: string;
  database_id: number;
  name: string;
  state: BlastIndexBuildState;
  db_type: BlastDatabaseType;
  index_identity?: string | null;
  sequence_count?: number | null;
  total_length?: number | null;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface BlastIndexBuildRequest {
  source_object_key: string;
  db_type: BlastDatabaseType;
  assembly_name: string;
  annotation_version: string;
  source_version: string;
  source_url: string;
  license: string;
  name: string;
  sequence_type?: BlastDatabase["sequence_type"];
}

/**
 * Acknowledgement for an accepted build request.
 *
 * Deliberately narrow: it says what was queued, never where the worker will
 * write it. Progress is read back from the catalog's `build_status`.
 */
export interface BlastIndexBuildQueued {
  database_id: number;
  queued: boolean;
  task_name: string;
}

/** Admin-only: enqueue a worker build. No makeblastdb runs in the request. */
export function requestBlastIndexBuild(payload: BlastIndexBuildRequest): Promise<BlastIndexBuild> {
  return http.post<BlastIndexBuild>("/blast/index-builds", { json: payload });
}

export function getBlastIndexBuild(buildId: string): Promise<BlastIndexBuild> {
  return http.get<BlastIndexBuild>(`/blast/index-builds/${encodeURIComponent(buildId)}`);
}
