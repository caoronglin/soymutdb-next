import { http } from "./auth";

export interface BlastDatabase {
  id: string | number;
  name: string;
  db_type: "nucl" | "prot";
  assembly_id: string | number;
  assembly_name?: string | null;
  assembly_version?: string | null;
  assembly_is_default?: boolean | null;
  is_active: boolean;
}

export interface BlastJob {
  id: string;
  name?: string;
  program: string;
  database: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  query_sequence: string;
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

export const BLAST_PROGRAMS = [
  { id: "blastn", label: "BLASTN", type: "nucleotide", description: "Nucleotide vs nucleotide" },
  { id: "blastp", label: "BLASTP", type: "protein", description: "Protein vs protein" },
  { id: "blastx", label: "BLASTX", type: "nucleotide", description: "Translated nucleotide vs protein" },
  { id: "tblastn", label: "TBLASTN", type: "protein", description: "Protein vs translated nucleotide" },
  { id: "tblastx", label: "TBLASTX", type: "nucleotide", description: "Translated nucleotide vs translated nucleotide" },
] as const;
