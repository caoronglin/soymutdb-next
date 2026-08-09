import { request } from "./client";

/**
 * Typed news endpoints (B1 public API).
 *
 * All three endpoints are public — `auth: false` keeps the in-memory Bearer
 * token off these requests. Response shapes mirror the backend schemas
 * (apps/api/app/schemas/news.py):
 *
 *   GET /api/v1/news?category=&page=&page_size=   → NewsListResponse
 *   GET /api/v1/news/featured                     → NewsFeaturedResponse
 *   GET /api/v1/news/{slug}?preview=&exp=         → NewsDetailResponse
 *
 * Note: the backend exposes bilingual titles/bodies (title_en/title_zh,
 * content_en/content_zh) and has NO summary field on list items; the
 * frontend selects the locale-appropriate title/body. Draft articles are
 * only reachable with a valid HMAC preview token (?preview=<token>&exp=<ts>,
 * 15 min) and 404 otherwise.
 */

/** News lifecycle status (backend `NewsStatus` StrEnum). */
export type NewsStatus = "draft" | "published" | "archived";

/** Public list-item view (no body content). */
export interface NewsSummary {
  id: string;
  title_en: string;
  title_zh: string | null;
  slug: string;
  category: string | null;
  cover_url: string | null;
  featured_sort: number;
  carousel_group: string | null;
  carousel_sort: number;
  status: NewsStatus;
  is_published: boolean;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Full article view — adds the (sanitised HTML) body content. */
export interface NewsDetail extends NewsSummary {
  content_en: string;
  content_zh: string | null;
}

/** Paginated public news list. */
export interface NewsListResponse {
  items: NewsSummary[];
  total: number;
  page: number;
  page_size: number;
}

/** One carousel group (grouped by carousel_group, ordered by carousel_sort). */
export interface NewsCarouselGroup {
  group: string;
  items: NewsSummary[];
}

/** Homepage block: 5 featured articles + carousel groups. */
export interface NewsFeaturedResponse {
  featured: NewsSummary[];
  carousel: NewsCarouselGroup[];
}

/**
 * List published news articles.
 *
 * @param category Optional category filter (backend stores lowercase values
 *   such as "news" / "update" / "announcement").
 * @param page 1-based page number (default 1).
 * @param pageSize Items per page (default 10, backend cap 200).
 */
export function listNews(
  category?: string,
  page = 1,
  pageSize = 10,
): Promise<NewsListResponse> {
  return request<NewsListResponse>("/news", {
    auth: false,
    params: { category, page, page_size: pageSize },
  });
}

/** Homepage block — featured articles + carousel groups. */
export function getFeaturedNews(): Promise<NewsFeaturedResponse> {
  return request<NewsFeaturedResponse>("/news/featured", { auth: false });
}

/**
 * Fetch a single article by slug.
 *
 * @param slug Article slug.
 * @param preview Optional HMAC preview token for unpublished/draft articles.
 * @param exp Optional preview token expiry timestamp (unix seconds).
 */
export function getNewsBySlug(
  slug: string,
  preview?: string,
  exp?: number,
): Promise<NewsDetail> {
  return request<NewsDetail>(`/news/${encodeURIComponent(slug)}`, {
    auth: false,
    params: { preview, exp },
  });
}
