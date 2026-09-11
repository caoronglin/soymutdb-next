import { http } from "./auth";

export interface ReleaseSummary {
  id: string;
  name: string;
  description?: string;
  assembly_id: string;
  assembly_name: string;
  // The release lifecycle vocabulary is owned by the backend database enum
  // (app/models/content.py ReleaseStatus) and surfaced by ReleaseResponse.
  status: "draft" | "validated" | "ready" | "published" | "rolled_back";
  release_date?: string;
  variant_count: number;
  gene_count: number;
  mutant_line_count: number;
  is_active: boolean;
  created_at: string;
}

export interface ReleaseDetail extends ReleaseSummary {
  provenance?: string;
  release_notes?: string;
  changelog?: string;
  extra?: Record<string, unknown>;
}

export interface ReleaseProvenance {
  id: string;
  release_id: string;
  source_type: string;
  source_name: string;
  source_url?: string;
  description?: string;
  version?: string;
  accession_date: string;
}

export interface ReleaseListParams {
  only_active?: boolean;
  page?: number;
  page_size?: number;
}

export function getReleases(params: ReleaseListParams = {}): Promise<ReleaseSummary[]> {
  return http.get<ReleaseSummary[]>("/releases", { params });
}

export function getRelease(releaseId: string): Promise<ReleaseDetail> {
  return http.get<ReleaseDetail>(`/releases/${releaseId}`);
}

export function getCurrentRelease(): Promise<ReleaseDetail> {
  return http.get<ReleaseDetail>("/releases/current");
}

export function getReleaseProvenance(releaseId: string): Promise<ReleaseProvenance[]> {
  return http.get<ReleaseProvenance[]>(`/releases/${releaseId}/provenance`);
}

export function getReleaseStats(releaseId: string): Promise<unknown> {
  return http.get<unknown>(`/releases/${releaseId}/stats`);
}
