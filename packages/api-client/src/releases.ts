import { http } from "./auth";
import type { components } from "./generated/openapi";

export type ReleaseSummary = components["schemas"]["ReleaseResponse"];

export interface ReleaseDetail extends ReleaseSummary {
  provenance?: string;
  release_notes?: string;
  changelog?: string;
  extra?: Record<string, unknown>;
}

export interface ReleaseListParams {
  status?: ReleaseSummary["status"];
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

/** Administrator-only private metadata; bypasses all shared server caches. */
export function getAdminReleases(params: ReleaseListParams = {}): Promise<ReleaseSummary[]> {
  return http.get<ReleaseSummary[]>("/releases", { params: { ...params, variant: "internal" } });
}

export function getAdminRelease(releaseId: string): Promise<ReleaseDetail> {
  return http.get<ReleaseDetail>(`/releases/${releaseId}`, { params: { variant: "internal" } });
}

// NOTE: this module may only touch the three routes the releases router
// actually registers — GET "" , GET "/active" and GET "/{release_id}" (see
// "apps/api/app/api/v1/releases.py"). There is no "/releases/current",
// "/releases/{id}/stats" or "/releases/{id}/provenance" route: read the active
// pointer through getActiveRelease() and release metadata through getRelease().
// Release administration lives on a separate "/admin/releases" router.
