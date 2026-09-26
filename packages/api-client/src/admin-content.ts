/**
 * Admin static-page content client.
 *
 * Typed wrappers over the administrator content API
 * (`apps/api/app/api/v1/admin_content.py` +
 * `apps/api/app/schemas/content.py`). The React console restored these pages
 * through a bespoke `StaticPage` type; this module is the single typed seam for
 * the Vue console.
 *
 *   GET    /admin/content/pages                        -> StaticPageListResponse
 *   POST   /admin/content/pages                        -> StaticPageDetail (201)
 *   GET    /admin/content/pages/{page_id}              -> StaticPageDetail
 *   PUT    /admin/content/pages/{page_id}              -> StaticPageDetail
 *   DELETE /admin/content/pages/{page_id}              -> 204
 *   POST   /admin/content/pages/{page_id}/publish      -> StaticPageDetail
 *   POST   /admin/content/pages/{page_id}/unpublish    -> StaticPageDetail
 *   GET    /admin/content/pages/{page_id}/versions     -> ContentVersion[]
 *   POST   /admin/content/pages/{page_id}/versions/{n}/restore -> StaticPageDetail
 *   POST   /admin/content/pages/migrate-to-page-builder/dry-run
 *          -> StaticPageMigrationDryRunReport (read-only preview)
 *
 * Every call goes through the coordinating `http` layer (refresh-on-401, retry,
 * logout events) with the in-memory Bearer token attached.
 */

import { http } from "./auth";

/** Lifecycle status shared by the page row and the create payload. */
export type StaticPageStatus = "draft" | "published" | "archived";

/** Page row as returned by the list and single-page endpoints. */
export interface StaticPage {
  id: string;
  slug: string;
  title_en: string;
  title_zh: string | null;
  content_en: string;
  content_zh: string | null;
  status: StaticPageStatus;
  category: string | null;
  summary: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

/** Extended page payload with authorship and current version metadata. */
export interface StaticPageDetail extends StaticPage {
  author_name: string | null;
  published_at: string | null;
  current_version: number;
}

/** List query parameters — mirrors the backend query arguments. */
export interface StaticPageListParams {
  status?: StaticPageStatus;
  category?: string;
  page?: number;
  page_size?: number;
}

/** Paginated list envelope returned by `GET /admin/content/pages`. */
export interface StaticPageListResponse {
  items: StaticPageDetail[];
  total: number;
}

/** Create payload — mirrors backend `StaticPageCreate`. */
export interface StaticPageCreatePayload {
  slug: string;
  title_en: string;
  title_zh?: string | null;
  content_en: string;
  content_zh?: string | null;
  summary?: string | null;
  category?: string | null;
  sort_order?: number;
  status?: StaticPageStatus;
  edit_comment?: string | null;
}

/** Update payload — mirrors backend `StaticPageUpdate` (partial). */
export interface StaticPageUpdatePayload {
  title_en?: string | null;
  title_zh?: string | null;
  content_en?: string | null;
  content_zh?: string | null;
  summary?: string | null;
  category?: string | null;
  sort_order?: number | null;
  edit_comment?: string | null;
}

/** One immutable revision snapshot of a page. */
export interface ContentVersion {
  id: string;
  page_id: string;
  version: number;
  title_en: string;
  title_zh: string | null;
  content_en: string;
  content_zh: string | null;
  summary: string | null;
  edited_by: string | null;
  edit_comment: string | null;
  created_at: string;
}

/** One row of the non-mutating legacy static-page migration preview. */
export interface StaticPageMigrationItem {
  static_page_id: number;
  slug: string;
  route: string;
  outcome: string;
  error_code: string | null;
  message: string | null;
}

/** Aggregate of the non-mutating legacy static-page migration preview. */
export interface StaticPageMigrationDryRunReport {
  dry_run: boolean;
  created: number;
  skipped: number;
  invalid: number;
  items: StaticPageMigrationItem[];
}

/** Optional unique-slug selection accepted by the dry-run endpoint. */
export interface StaticPageMigrationDryRunRequest {
  slugs?: string[] | null;
}

/** List every static page (including drafts) with optional filters. */
export function listStaticPages(
  params: StaticPageListParams = {},
): Promise<StaticPageListResponse> {
  const query: Record<string, string> = {};
  if (params.status) query.status = params.status;
  if (params.category) query.category = params.category;
  if (params.page) query.page = String(params.page);
  if (params.page_size) query.page_size = String(params.page_size);
  return http.get<StaticPageListResponse>("/admin/content/pages", { params: query });
}

/** Fetch one page, drafts included, for the editor. */
export function getStaticPage(pageId: number | string): Promise<StaticPageDetail> {
  return http.get<StaticPageDetail>(`/admin/content/pages/${pageId}`);
}

/** Create a page and its first content version. */
export function createStaticPage(
  payload: StaticPageCreatePayload,
): Promise<StaticPageDetail> {
  return http.post<StaticPageDetail>("/admin/content/pages", { json: payload });
}

/** Apply a partial update; the server snapshots a new content version. */
export function updateStaticPage(
  pageId: number | string,
  payload: StaticPageUpdatePayload,
): Promise<StaticPageDetail> {
  return http.put<StaticPageDetail>(`/admin/content/pages/${pageId}`, { json: payload });
}

/** Delete a page and its versions (204). */
export function deleteStaticPage(pageId: number | string): Promise<void> {
  return http.delete<void>(`/admin/content/pages/${pageId}`);
}

/** Publish a page and record the publication time. */
export function publishStaticPage(
  pageId: number | string,
): Promise<StaticPageDetail> {
  return http.post<StaticPageDetail>(`/admin/content/pages/${pageId}/publish`);
}

/** Return a published page to draft. */
export function unpublishStaticPage(
  pageId: number | string,
): Promise<StaticPageDetail> {
  return http.post<StaticPageDetail>(`/admin/content/pages/${pageId}/unpublish`);
}

/** List a page's content versions, newest first. */
export function listStaticPageVersions(
  pageId: number | string,
): Promise<ContentVersion[]> {
  return http.get<ContentVersion[]>(`/admin/content/pages/${pageId}/versions`);
}

/** Restore a previous version as a new head version. */
export function restoreStaticPageVersion(
  pageId: number | string,
  version: number,
): Promise<StaticPageDetail> {
  return http.post<StaticPageDetail>(
    `/admin/content/pages/${pageId}/versions/${version}/restore`,
  );
}

/**
 * Preview the one-way legacy StaticPage -> page-builder migration.
 *
 * The endpoint is read-only by contract (`dry_run: true`); it never creates,
 * publishes, or mutates a page. Callers must surface it as a diagnostic only.
 */
export function dryRunStaticPageMigration(
  payload: StaticPageMigrationDryRunRequest = {},
): Promise<StaticPageMigrationDryRunReport> {
  return http.post<StaticPageMigrationDryRunReport>(
    "/admin/content/pages/migrate-to-page-builder/dry-run",
    { json: payload },
  );
}

/** Grouped namespace mirroring the function exports for discoverability. */
export const adminContentApi = {
  list: listStaticPages,
  get: getStaticPage,
  create: createStaticPage,
  update: updateStaticPage,
  remove: deleteStaticPage,
  publish: publishStaticPage,
  unpublish: unpublishStaticPage,
  versions: listStaticPageVersions,
  restore: restoreStaticPageVersion,
  dryRunMigration: dryRunStaticPageMigration,
};
