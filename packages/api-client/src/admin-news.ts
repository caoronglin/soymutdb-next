/**
 * Admin news operations client (B3) — typed wrappers over the B1 admin API.
 *
 * Contract (apps/api/app/api/v1/admin_news.py + apps/api/app/schemas/news.py):
 *
 *   GET    /api/v1/admin/news                     -> NewsListResponse (all statuses)
 *   POST   /api/v1/admin/news                     NewsCreate   -> NewsDetail (201)
 *   PUT    /api/v1/admin/news/{news_id}           NewsUpdate   -> NewsDetail
 *   DELETE /api/v1/admin/news/{news_id}           -> 204 (soft delete)
 *   GET    /api/v1/admin/news/deleted             -> DeletedAdminNewsListResponse
 *   POST   /api/v1/admin/news/{news_id}/restore    -> NewsDetail
 *   DELETE /api/v1/admin/news/{news_id}/purge      -> 204 (permanent delete)
 *   PATCH  /api/v1/admin/news/reorder           NewsReorderRequest -> NewsReorderResponse
 *   GET    /api/v1/admin/news/{news_id}/preview-token -> PreviewTokenResponse
 *   GET    /api/v1/admin/news/{news_id}         (via preview-token dance) -> NewsDetail
 *
 * All admin calls go through the `http` coordinating layer (refresh-on-401,
 * retry, logout events) with the in-memory Bearer token attached.
 */

import type {
  ExternalArticlePlatform,
  NewsDetail,
  NewsSummary,
  NewsStatus,
} from "./news";
import { getNewsBySlug } from "./news";
import { http } from "./auth";

export type { ExternalArticlePlatform, NewsStatus };

/** Full article view as returned by admin create/update (bilingual body). */
export type AdminNewsDetail = NewsDetail;

/** List item with lifecycle status (backend NewsSummaryResponse). */
export type AdminNewsItem = NewsSummary;

/** Admin list query params — mirrors backend query parameters. */
export interface AdminNewsListParams {
  status_filter?: NewsStatus;
  category?: string;
  search?: string;
  page?: number;
  page_size?: number;
}

/** Admin list response — same shape as public NewsListResponse. */
export interface AdminNewsListResponse {
  items: NewsSummary[];
  total: number;
  page: number;
  page_size: number;
}

/** Metadata-only item returned from the administrator trash. */
export interface DeletedAdminNewsItem {
  id: number;
  title_en: string;
  title_zh: string | null;
  slug: string;
  category: string | null;
  status: NewsStatus;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string;
}

/** Paginated administrator trash response. */
export interface DeletedAdminNewsListResponse {
  items: DeletedAdminNewsItem[];
  total: number;
  page: number;
  page_size: number;
}

/** Administrator-trash pagination parameters accepted by the server. */
export interface DeletedAdminNewsListParams {
  page?: number;
  page_size?: number;
}

/** Create payload — mirrors backend `NewsCreate`. */
export interface NewsCreatePayload {
  title_en: string;
  title_zh?: string | null;
  content_en: string;
  content_zh?: string | null;
  slug: string;
  category?: string | null;
  cover_url?: string | null;
  cover_asset_id?: string | null;
  cover_alt_text?: string | null;
  featured_sort?: number;
  carousel_group?: string | null;
  carousel_sort?: number;
  status?: NewsStatus;
  visible_from?: string | null;
  visible_to?: string | null;
  /** Opaque short-lived proof returned by external-preview. */
  source_preview_token?: string;
}

/** Update payload — mirrors backend `NewsUpdate` (partial; all optional). */
export interface NewsUpdatePayload {
  title_en?: string | null;
  title_zh?: string | null;
  content_en?: string | null;
  content_zh?: string | null;
  slug?: string | null;
  category?: string | null;
  cover_url?: string | null;
  cover_asset_id?: string | null;
  cover_alt_text?: string | null;
  featured_sort?: number | null;
  carousel_group?: string | null;
  carousel_sort?: number | null;
  status?: NewsStatus;
  visible_from?: string | null;
  visible_to?: string | null;
  is_published?: boolean | null;
  /** Replace attribution only with a fresh external preview attestation. */
  source_preview_token?: string | null;
  /** Explicitly remove any existing external-source attribution. */
  clear_source_provenance?: boolean;
}

/** Sanitized, non-persistent result of an approved external source preview. */
export interface ExternalArticlePreview {
  platform: ExternalArticlePlatform;
  source_url: string;
  title: string;
  content_html: string;
  /** Opaque short-lived proof used when the normal news form is saved. */
  source_preview_token: string;
  source_published_at: string | null;
}

export interface ExternalArticlePreviewRequest {
  platform: ExternalArticlePlatform;
  source_url: string;
}

/** Reorder item — `featured_sort` is 0-based drag order. */
export interface NewsReorderItem {
  id: number;
  featured_sort: number;
}

/** Reorder payload — mirrors backend `NewsReorderRequest`. */
export interface NewsReorderRequest {
  items: NewsReorderItem[];
}

/** Reorder result — mirrors backend `NewsReorderResponse`. */
export interface NewsReorderResponse {
  updated: number;
}

/** HMAC preview token (15 min, stateless) — mirrors `PreviewTokenResponse`. */
export interface NewsPreviewToken {
  preview: string;
  exp: number;
  url: string;
}

/**
 * List ALL news articles (researcher+) — including drafts and archived.
 * Supports status_filter, category, search (title ILIKE), and pagination.
 */
export function listAdminNews(
  params: AdminNewsListParams = {},
): Promise<AdminNewsListResponse> {
  const query: Record<string, string> = {};
  if (params.status_filter) query.status_filter = params.status_filter;
  if (params.category) query.category = params.category;
  if (params.search) query.search = params.search;
  if (params.page) query.page = String(params.page);
  if (params.page_size) query.page_size = String(params.page_size);
  return http.get<AdminNewsListResponse>("/admin/news", { params: query });
}


/** List soft-deleted news metadata in the administrator trash. */
export function listDeletedAdminNews(
  params: DeletedAdminNewsListParams = {},
): Promise<DeletedAdminNewsListResponse> {
  const query: Record<string, string> = {};
  if (params.page) query.page = String(params.page);
  if (params.page_size) query.page_size = String(params.page_size);
  return http.get<DeletedAdminNewsListResponse>("/admin/news/deleted", {
    params: query,
  });
}

/**
 * Fetch and sanitize one approved WeChat/X-MOL article for human review.
 * This endpoint never writes or publishes a news record.
 */
export function previewExternalNewsArticle(
  payload: ExternalArticlePreviewRequest,
): Promise<ExternalArticlePreview> {
  return http.post<ExternalArticlePreview>("/admin/news/external-preview", { json: payload });
}

/** Create a news article (draft by default; publish via `status`). */
export function createNews(payload: NewsCreatePayload): Promise<AdminNewsDetail> {
  return http.post<AdminNewsDetail>("/admin/news", { json: payload });
}

/** Partial update of a news article (status/is_published double-write). */
export function updateNews(
  newsId: number | string,
  payload: NewsUpdatePayload,
): Promise<AdminNewsDetail> {
  return http.put<AdminNewsDetail>(`/admin/news/${newsId}`, { json: payload });
}

/** Move a news article to the recoverable administrator trash (204). */
export function deleteNews(newsId: number | string): Promise<void> {
  return http.delete<void>(`/admin/news/${newsId}`);
}


/** Restore a soft-deleted news article from the administrator trash. */
export function restoreNews(newsId: number | string): Promise<AdminNewsDetail> {
  return http.post<AdminNewsDetail>(`/admin/news/${newsId}/restore`);
}

/** Permanently delete a soft-deleted news article (204). */
export function purgeNews(newsId: number | string): Promise<void> {
  return http.delete<void>(`/admin/news/${newsId}/purge`);
}

/** Apply a full drag-and-drop ordering of `featured_sort` values. */
export function reorderNews(
  items: NewsReorderItem[],
): Promise<NewsReorderResponse> {
  return http.patch<NewsReorderResponse>("/admin/news/reorder", {
    json: { items } satisfies NewsReorderRequest,
  });
}

/** Mint a 15-minute HMAC preview token for a (draft/hidden) article. */
export function getPreviewToken(
  newsId: number | string,
): Promise<NewsPreviewToken> {
  return http.get<NewsPreviewToken>(`/admin/news/${newsId}/preview-token`);
}

/**
 * Fetch the full detail of any article (draft/published/archived) for the
 * edit page.
 *
 * B1 has no `GET /admin/news/{news_id}` endpoint, so this uses the HMAC
 * preview-token dance: mint a token for the id, derive the slug from the
 * returned URL, then read the public detail with the token (which unlocks
 * non-visible articles — see apps/api/app/services/news_service.py
 * `get_by_slug`).
 */
export async function getAdminNewsDetail(
  newsId: number | string,
): Promise<NewsDetail> {
  const token = await getPreviewToken(newsId);
  // token.url = "/api/v1/news/{slug}?preview=<token>&exp=<ts>"
  const match = token.url.match(/\/news\/([^/?]+)/);
  if (!match) {
    throw new Error(`Cannot derive slug from preview url: ${token.url}`);
  }
  return getNewsBySlug(decodeURIComponent(match[1]), token.preview, token.exp);
}
