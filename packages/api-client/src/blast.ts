import { http } from "./auth";
import { ApiError } from "./client";
import type { AssemblyInfo, GeneDetail } from "./genes";

export interface BlastDatabase {
  id: string | number;
  name: string;
  db_type: "nucl" | "prot";
  assembly_id: string | number;
  assembly_name?: string | null;
  assembly_version?: string | null;
  assembly_is_default?: boolean | null;
  release_id?: number | null;
  is_active: boolean;
}

export interface BlastJob {
  id: string;
  name?: string;
  program: string;
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
}

export interface BlastJobParams {
  program: string;
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
}

export function getBlastDatabases(): Promise<BlastDatabase[]> {
  return http.get<BlastDatabase[]>("/blast/databases");
}

export function submitBlastJob(params: BlastJobParams): Promise<BlastJob> {
  return http.post<BlastJobApi>("/blast/jobs", {
    json: {
      program: params.program,
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
}

function normalizeJob(job: BlastJobApi | BlastJob): BlastJob {
  if ("id" in job) return job;
  return {
    ...job,
    id: job.job_id,
    database: job.database ?? String(job.database_id),
  };
}

/** The only submittable program. Stored jobs may still report the wider
 *  {@link BlastProgram} vocabulary, which is why this is a one-entry list
 *  rather than a type alias. */
export const BLAST_PROGRAMS = [
  { id: "blastp", label: "BLASTP", type: "protein", description: "Protein vs protein" },
] as const;
