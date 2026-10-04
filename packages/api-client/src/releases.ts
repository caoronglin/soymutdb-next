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

/** The release the public surface currently serves (`active_release` singleton). */
export interface ActiveRelease {
  /** null before the first publish. */
  release_id: string | null;
  version: string | null;
  published_at: string | null;
}

/**
 * Read the active release pointer.
 *
 * Safe to call while the tab is pinned to an older release: the endpoint does
 * not depend on `get_release_context`, it reads the `active_release` singleton
 * directly, so a stale `X-SoyMutDB-Release` header cannot make it report the
 * release the caller already knows.
 */
export function getActiveRelease(): Promise<ActiveRelease> {
  return http.get<ActiveRelease>("/releases/active");
}

export function getReleases(params: ReleaseListParams = {}): Promise<ReleaseSummary[]> {
  return http.get<ReleaseSummary[]>("/releases", { params });
}

export function getRelease(releaseId: string): Promise<ReleaseDetail> {
  return http.get<ReleaseDetail>(`/releases/${releaseId}`);
}

export function getReleaseProvenance(releaseId: string): Promise<ReleaseProvenance[]> {
  return http.get<ReleaseProvenance[]>(`/releases/${releaseId}/provenance`);
}

// NOTE: there is no `/releases/current` or `/releases/{id}/stats` route on the
// API. The active release is the `is_active` row of `getReleases()`; a function
// that points at a missing route is a 422 waiting for the next caller.
