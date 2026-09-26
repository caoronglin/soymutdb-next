/**
 * Admin analytics summary client.
 *
 * Typed wrapper over `GET /api/v1/admin/analytics/summary`
 * (`apps/api/app/api/v1/analytics.py` + `AnalyticsService.get_summary`). The
 * endpoint is administrator-only and returns a fixed aggregate shape; the
 * backend types it as `dict[str, Any]`, so this module pins the field names the
 * dashboard renders rather than consuming `unknown`.
 */

import { http } from "./auth";

/** One labelled bucket in a breakdown list (type / page / referrer / search). */
export interface AdminAnalyticsBreakdownItem {
  label: string;
  count: number;
}

/** Aggregated visitor metrics over a bounded day window. */
export interface AdminAnalyticsSummary {
  total_events: number;
  unique_sessions: number;
  events_by_type: AdminAnalyticsBreakdownItem[];
  top_pages: AdminAnalyticsBreakdownItem[];
  top_referrers: AdminAnalyticsBreakdownItem[];
  top_searches: AdminAnalyticsBreakdownItem[];
  events_by_day: AdminAnalyticsBreakdownItem[];
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
