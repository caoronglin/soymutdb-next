/**
 * Admin news operations client (B3) — typed wrappers over the B1 admin API.
 *
 * Contract (apps/api/app/api/v1/admin_news.py + apps/api/app/schemas/news.py):
 *
 *   GET    /api/v1/admin/news                     -> NewsListResponse (all statuses)
 *   POST   /api/v1/admin/news                     NewsCreate   -> NewsDetail (201)
 *   PUT    /api/v1/admin/news/{news_id}           NewsUpdate   -> NewsDetail
 *   DELETE /api/v1/admin/news/{news_id}           -> 204
 *   PATCH  /api/v1/admin/news/reorder           NewsReorderRequest -> NewsReorderResponse
 *   GET    /api/v1/admin/news/{news_id}/preview-token -> PreviewTokenResponse
 *   GET    /api/v1/admin/news/{news_id}         (via preview-token dance) -> NewsDetail
 *
 * All admin calls go through the `http` coordinating layer (refresh-on-401,
 * retry, logout events) with the in-memory Bearer token attached.
 */

import type { NewsDetail, NewsSummary, NewsStatus } from "./news";
import { getNewsBySlug } from "./news";
import { http } from "./auth";

export type { NewsStatus };

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

/** Hard-delete a news article (204). */
export function deleteNews(newsId: number | string): Promise<void> {
  return http.delete<void>(`/admin/news/${newsId}`);
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
