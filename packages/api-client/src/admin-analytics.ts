/**
 * Admin analytics summary client.
 *
 * Typed wrapper over `GET /api/v1/admin/analytics/summary`
 * (`apps/api/app/api/v1/analytics.py` + `AnalyticsService.get_summary`). The
 * endpoint is administrator-only; its response is the backend schema
 * `AnalyticsSummary`, so the types below mirror that contract field for field
 * (the seven data sections plus the seven `*_available` flags).
 *
 * What a caller may rely on:
 *
 * - every label is a constant produced by the server: a canonical route
 *   template (`/mutants/:publicId`, `/other`), one of the four referrer
 *   categories (`direct` | `search` | `social` | `other`), a finite event
 *   type, or a `YYYY-MM-DD` day. A raw identifier, a query string, a full URL
 *   or a free-text search term is never returned;
 * - `top_searches` is always empty and `top_searches_available` is always
 *   `false`: search terms are not collected, so nothing is queried or shown;
 * - `*_available === false` means the analytics store could not be read. Do
 *   not render an unavailable section as "zero visits".
 */

import { http } from "./auth";

/** One labelled bucket in a breakdown list (type / page / referrer / day). */
export interface AdminAnalyticsBreakdownItem {
  label: string;
  count: number;
}

/** Aggregated visitor metrics over a bounded day window. */
export interface AdminAnalyticsSummary {
  total_events: number;
  unique_sessions: number;
  events_by_type: AdminAnalyticsBreakdownItem[];
  /** Canonical route templates only, counts merged across equal templates. */
  top_pages: AdminAnalyticsBreakdownItem[];
  /** The four referrer categories only; a client-supplied header hint. */
  top_referrers: AdminAnalyticsBreakdownItem[];
  /** Always empty: free-text search terms are not collected. */
  top_searches: AdminAnalyticsBreakdownItem[];
  events_by_day: AdminAnalyticsBreakdownItem[];
  /** `false` means the analytics store could not be read, not "no traffic". */
  total_events_available: boolean;
  unique_sessions_available: boolean;
  events_by_type_available: boolean;
  top_pages_available: boolean;
  top_referrers_available: boolean;
  /** Always `false`, like `top_searches` itself. */
  top_searches_available: boolean;
  events_by_day_available: boolean;
}

export interface AdminAnalyticsSummaryParams {
  /** Window size in days (server accepts 1..365). */
  days?: number;
}

/** Fetch aggregate analytics metrics for the administrator dashboard. */
export function getAdminAnalyticsSummary(
  params: AdminAnalyticsSummaryParams = {},
): Promise<AdminAnalyticsSummary> {
  const query: Record<string, string> = {};
  if (params.days) query.days = String(params.days);
  return http.get<AdminAnalyticsSummary>("/admin/analytics/summary", {
    params: query,
  });
}