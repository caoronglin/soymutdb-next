/**
 * Widget management API client for the admin console.
 *
 * Endpoints:
 *   GET    /api/v1/admin/widgets              — list all widgets
 *   GET    /api/v1/admin/widgets/:name        — get single widget
 *   POST   /api/v1/admin/widgets              — create widget
 *   PUT    /api/v1/admin/widgets/:name        — update widget
 *   DELETE /api/v1/admin/widgets/:name        — delete widget
 *   POST   /api/v1/admin/widgets/:name/preview — render preview with params
 *   GET    /api/v1/admin/widgets/health       — widget health metrics
 *   GET    /api/v1/admin/layout/:page         — get layout for a page
 *   PUT    /api/v1/admin/layout/:page         — update layout for a page
 */

import { http } from "@soymutdb/api-client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type WidgetCategory =
  | "stats"
  | "chart"
  | "table"
  | "list"
  | "search"
  | "navigation"
  | "content"
  | "custom";

export type WidgetPermission = "public" | "user" | "editor" | "admin";

export interface WidgetDefinition {
  name: string;
  display_name: string;
  description: string | null;
  category: WidgetCategory;
  template_path: string;
  data_source: string | null;
  params_schema: Record<string, unknown> | null;
  cache_ttl: number;
  admin_config: Record<string, unknown> | null;
  permissions: WidgetPermission;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface WidgetListResponse {
  items: WidgetDefinition[];
  total: number;
}

export interface WidgetPreviewRequest {
  params: Record<string, unknown>;
}

export interface WidgetPreviewResponse {
  html: string;
  latency_ms: number;
}

export interface WidgetHealthItem {
  name: string;
  display_name: string;
  p50_ms: number;
  p95_ms: number;
  cache_hit_rate: number;
  error_count: number;
  request_count: number;
  /** Time-series points for cache-hit rate trend. */
  cache_hit_history: Array<{ timestamp: string; rate: number }>;
  /** Time-series points for latency trend. */
  latency_history: Array<{ timestamp: string; p50: number; p95: number }>;
}

export interface WidgetHealthResponse {
  widgets: WidgetHealthItem[];
  generated_at: string;
}

export interface LayoutWidget {
  name: string;
  /** Optional per-instance configuration overrides. */
  config?: Record<string, unknown>;
  /** Optional region/column (for multi-column layouts). */
  region?: string;
}

export interface PageLayout {
  page: string;
  widgets: LayoutWidget[];
  updated_at?: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export const widgetApi = {
  /** List all widgets (paginated). */
  list(params?: { page?: number; page_size?: number; category?: string }) {
    return http.get<WidgetListResponse>("/admin/widgets", { params });
  },

  /** Get a single widget by name. */
  get(name: string) {
    return http.get<WidgetDefinition>(`/admin/widgets/${encodeURIComponent(name)}`);
  },

  /** Create a new widget. */
  create(payload: Omit<WidgetDefinition, "created_at" | "updated_at">) {
    return http.post<WidgetDefinition>("/admin/widgets", { json: payload });
  },

  /** Update an existing widget. */
  update(name: string, payload: Partial<WidgetDefinition>) {
    return http.put<WidgetDefinition>(`/admin/widgets/${encodeURIComponent(name)}`, {
      json: payload,
    });
  },

  /** Delete a widget. */
  remove(name: string) {
    return http.delete<void>(`/admin/widgets/${encodeURIComponent(name)}`);
  },

  /** Render a widget preview with the supplied params. */
  preview(name: string, payload: WidgetPreviewRequest) {
    return http.post<WidgetPreviewResponse>(
      `/admin/widgets/${encodeURIComponent(name)}/preview`,
      { json: payload },
    );
  },

  /** Fetch health metrics for all widgets. */
  health() {
    return http.get<WidgetHealthResponse>("/admin/widgets/health");
  },

  /** Get the widget layout for a specific page. */
  getLayout(page: string) {
    return http.get<PageLayout>(`/admin/layout/${encodeURIComponent(page)}`);
  },

  /** Update the widget layout for a page. */
  saveLayout(page: string, widgets: LayoutWidget[]) {
    return http.put<PageLayout>(`/admin/layout/${encodeURIComponent(page)}`, {
      json: { widgets },
    });
  },
};

export default widgetApi;
