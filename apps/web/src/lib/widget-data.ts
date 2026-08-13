/**
 * Widget data types and helper functions for SoyMutDB Next.
 *
 * Shared between the SSG build scripts and the runtime widget-loader so that
 * widget descriptor shapes are consistent across the stack.
 */

/** Widget descriptor returned by GET /api/v1/layout/{page} */
export interface WidgetDescriptor {
  name: string;
  display_name: string;
  category:
    | "hero"
    | "navigation"
    | "search"
    | "data_table"
    | "detail"
    | "visualization"
    | "stats"
    | "external"
    | "layout"
    | "custom";
  params_schema: Record<string, unknown>;
  cache_ttl: number;
}

/** Layout response shape */
export interface LayoutResponse {
  page_name: string;
  display_name: string;
  widgets: WidgetDescriptor[];
}

/** Widget render modes */
export type WidgetRenderMode = "static" | "dynamic";

/**
 * Decide whether a widget should be statically inlined at SSG build time
 * or fetched dynamically at runtime.
 *
 * Static widgets have a long TTL (>= 60s) and no external data dependencies
 * that change per-request.  Dynamic widgets (short TTL, external data sources)
 * are left as runtime placeholders.
 */
export function getWidgetRenderMode(widget: WidgetDescriptor): WidgetRenderMode {
  // Widgets with very short/zero TTL are dynamic
  if (widget.cache_ttl < 30) return "dynamic";
  // Known dynamic categories
  if (widget.category === "external" || widget.category === "search") return "dynamic";
  return "static";
}

/** Build query string for widget params */
export function buildWidgetParams(params: Record<string, unknown>): string {
  return encodeURIComponent(JSON.stringify(params));
}

/** Widget fetch endpoint */
export function widgetEndpoint(name: string, params?: Record<string, unknown>): string {
  const base = `${import.meta.env.BASE_URL}api/v1/widget/${encodeURIComponent(name)}`;
  if (!params || Object.keys(params).length === 0) return base;
  return `${base}?params=${buildWidgetParams(params)}`;
}
