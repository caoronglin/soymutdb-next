/**
 * Content snapshot + bootstrap JSON consumption (E3).
 *
 * SSG pages (built by E2's ssg-content.ts) embed the current page's data in
 * a `<script type="application/json" id="rl-bootstrap">` tag and ship a
 * site-wide snapshot at `<base>/data/content.json`. On CSR startup the page
 * component reads the bootstrap synchronously, prefills the TanStack Query
 * cache (so the first paint renders snapshot data — no loading flash), then
 * lets the API refresh in the background.
 *
 * Frozen contract (docs/design/static-content-richtext-2026-08.md §4.1/§5):
 *   - snapshot JSON: { schema_version, generated_at, news, news_detail, about }
 *   - bootstrap JSON: { page: "news-list"|"news-detail"|"about",
 *       category?, slug?, data, generated_at }
 *   - preview/exp requests always hit the API — never prefilled.
 */
import type { QueryClient } from "@tanstack/react-query";
import type { NewsDetail, NewsListResponse, NewsSummary } from "@soymutdb/api-client";

/** News block of the site-wide snapshot. */
export interface SnapshotNews {
  source_total: number;
  included_total: number;
  truncated: boolean;
  /** Public-visible summaries, published-at descending, capped at 500. */
  items: NewsSummary[];
}

/** About block — mirrors GET /site/about (all fields optional). */
export interface SnapshotAbout {
  title_en: string | null;
  title_zh: string | null;
  summary_en: string | null;
  summary_zh: string | null;
  content_en: string | null;
  content_zh: string | null;
}

/** Site-wide snapshot shipped at `<base>/data/content.json`. */
export interface Snapshot {
  schema_version: number;
  generated_at: string;
  news: SnapshotNews;
  /**
   * Slug → full detail. Visibility-window articles are explicitly null
   * (never statically generated) — detail pages for those fall back to API.
   */
  news_detail: Record<string, NewsDetail | null>;
  about: SnapshotAbout | null;
}

/** Per-page bootstrap payload embedded by SSG pages. */
export interface BootstrapPayload {
  page: "news-list" | "news-detail" | "about";
  /** News list only — category the static page was generated for. */
  category?: string;
  /** News detail only — the generated article slug. */
  slug?: string;
  /** Page data — shape depends on `page` (NewsListResponse / NewsDetail / SnapshotAbout). */
  data: unknown;
  generated_at: string;
}

const BOOTSTRAP_ID = "rl-bootstrap";

const BOOTSTRAP_PAGES = ["news-list", "news-detail", "about"] as const;

function isBootstrapPage(value: unknown): value is BootstrapPayload["page"] {
  return typeof value === "string" && (BOOTSTRAP_PAGES as readonly string[]).includes(value);
}

/**
 * Read the embedded bootstrap JSON of the current page.
 *
 * Synchronous and cheap — call during first render. Returns null when the
 * tag is missing, unparsable, or not a recognised payload (plain SPA dev).
 */
export function readBootstrap(): BootstrapPayload | null {
  if (typeof document === "undefined") return null;
  const el = document.getElementById(BOOTSTRAP_ID);
  if (!el) return null;
  try {
    const raw = JSON.parse(el.textContent ?? "") as Record<string, unknown>;
    if (!raw || typeof raw !== "object" || !isBootstrapPage(raw.page)) return null;
    if (typeof raw.generated_at !== "string") return null;
    if (!raw.data || typeof raw.data !== "object") return null;
    return raw as unknown as BootstrapPayload;
  } catch {
    return null;
  }
}

/**
 * Fetch the site-wide snapshot JSON. Never throws — missing/parse failures
 * degrade to null so callers fall back to the pure-API path.
 *
 * The URL is anchored with `import.meta.env.BASE_URL` because relative
 * "data/content.json" resolves against the current route (e.g. /news/xxx)
 * and would 404 on gh-pages.
 */
export async function loadSnapshotJson(): Promise<Snapshot | null> {
  const url = `${import.meta.env.BASE_URL}data/content.json`;
  try {
    const res = await fetch(url, { credentials: "omit" });
    if (!res.ok) return null;
    const json = (await res.json()) as Partial<Snapshot>;
    if (!json || typeof json !== "object" || json.schema_version !== 1) return null;
    if (typeof json.generated_at !== "string") return null;
    return json as Snapshot;
  } catch {
    return null;
  }
}

/**
 * Parse a snapshot `generated_at` ISO string to a numeric timestamp, or
 * undefined when invalid (defensive — callers pass it to
 * `initialDataUpdatedAt`, which must not be NaN).
 */
export function snapshotTimestamp(generatedAt: string | undefined): number | undefined {
  if (!generatedAt) return undefined;
  const ms = new Date(generatedAt).getTime();
  return Number.isFinite(ms) ? ms : undefined;
}

/**
 * Prefill one query cache entry with snapshot data.
 *
 * `setQueryData(..., { updatedAt })` pins the cache timestamp to the
 * snapshot's generation time, so the entry is already stale relative to
 * `Date.now()` — the query's next background refetch replaces the snapshot
 * with fresh API data. Returns the numeric updatedAt for callers that want
 * to derive their own staleness window.
 */
export function prefillQueryData<T>(
  queryClient: QueryClient,
  queryKey: readonly unknown[],
  data: T,
  generatedAt: string,
): number {
  const updatedAt = new Date(generatedAt).getTime();
  if (Number.isFinite(updatedAt)) {
    queryClient.setQueryData(queryKey, data, { updatedAt });
  } else {
    queryClient.setQueryData(queryKey, data);
  }
  return updatedAt;
}

/** Runtime guard: is the bootstrap data a list response we can prefill? */
export function isListResponseData(value: unknown): value is NewsListResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as NewsListResponse).items) &&
    typeof (value as NewsListResponse).total === "number"
  );
}

/** Runtime guard: is the bootstrap data a news detail we can prefill? */
export function isDetailData(value: unknown): value is NewsDetail {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as NewsDetail).slug === "string" &&
    typeof (value as NewsDetail).content_en === "string"
  );
}

/** Runtime guard: is the bootstrap data an about payload we can prefill? */
export function isAboutData(value: unknown): value is SnapshotAbout {
  return (
    typeof value === "object" &&
    value !== null &&
    ("title_en" in value || "content_en" in value)
  );
}
