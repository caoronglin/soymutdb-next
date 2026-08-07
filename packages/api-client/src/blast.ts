import { http } from "./client";

export interface BlastDatabase {
  id: string;
  name: string;
  type: "nucleotide" | "protein";
  description: string;
  sequence_count: number;
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
  id: string;
  job_id: string;
  target_id: string;
  target_description?: string;
  score: number;
  e_value: number;
  identity: number;
  identity_percent: number;
  alignment_length: number;
  query_start: number;
  query_end: number;
  target_start: number;
  target_end: number;
  gaps: number;
  query_sequence: string;
  target_sequence: string;
  midline: string;
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
  return http.post<BlastJob>("/blast/jobs", { json: params });
}

export function getBlastJobs(params: {
  page?: number;
  page_size?: number;
  status?: string;
} = {}): Promise<BlastJobListResponse> {
  return http.get<BlastJobListResponse>("/blast/jobs", { params });
}

export function getBlastJob(jobId: string): Promise<BlastJob> {
  return http.get<BlastJob>(`/blast/jobs/${jobId}`);
}

export function getBlastHits(
  jobId: string,
  params: {
    page?: number;
    page_size?: number;
    min_e_value?: number;
    min_identity?: number;
  } = {},
): Promise<BlastHitListResponse> {
  return http.get<BlastHitListResponse>(`/blast/jobs/${jobId}/hits`, { params });
}

export function cancelBlastJob(jobId: string): Promise<void> {
  return http.post<void>(`/blast/jobs/${jobId}/cancel`);
}

export const BLAST_PROGRAMS = [
  { id: "blastn", label: "BLASTN", type: "nucleotide", description: "Nucleotide vs nucleotide" },
  { id: "blastp", label: "BLASTP", type: "protein", description: "Protein vs protein" },
  { id: "blastx", label: "BLASTX", type: "nucleotide", description: "Translated nucleotide vs protein" },
  { id: "tblastn", label: "TBLASTN", type: "protein", description: "Protein vs translated nucleotide" },
  { id: "tblastx", label: "TBLASTX", type: "nucleotide", description: "Translated nucleotide vs translated nucleotide" },
] as const;
