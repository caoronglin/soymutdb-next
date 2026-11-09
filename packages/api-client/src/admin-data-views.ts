/**
 * Saved multi-view configurations over the release-scoped public read APIs.
 *
 * A view is presentation only: it names a public source (`genes`, `variants`,
 * `mutant_lines`), the fields to show, and the filters/sort/grouping the
 * operator chose. Rows are always fetched from the same public list endpoints
 * the portal uses, so a saved view can never widen visibility to unreleased
 * records or internal identifiers.
 */
import { http } from "./auth";
import { searchGenes } from "./genes";
import { listMutantLines } from "./mutant-lines";
import { searchVariants } from "./variants";

export type DataViewSource = "genes" | "variants" | "mutant_lines";
export type DataViewKind = "grid" | "kanban" | "gallery";
export type DataViewSortDir = "asc" | "desc";

export const DATA_VIEW_SOURCES: readonly DataViewSource[] = [
  "genes",
  "variants",
  "mutant_lines",
];

export const DATA_VIEW_KINDS: readonly DataViewKind[] = ["grid", "kanban", "gallery"];

export interface DataViewSourceInfo {
  source: DataViewSource;
  fields: string[];
  filter_fields: string[];
  default_fields: string[];
}

export interface AdminDataView {
  id: number;
  name: string;
  source: DataViewSource;
  view_type: DataViewKind;
  visible_fields: string[];
  filters: Record<string, string>;
  sort_field: string | null;
  sort_dir: DataViewSortDir | null;
  group_field: string | null;
  title_field: string | null;
  page_size: number;
  is_default: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminDataViewInput {
  name: string;
  source: DataViewSource;
  view_type?: DataViewKind;
  visible_fields: string[];
  filters?: Record<string, string>;
  sort_field?: string | null;
  sort_dir?: DataViewSortDir | null;
  group_field?: string | null;
  title_field?: string | null;
  page_size?: number;
  is_default?: boolean;
  notes?: string | null;
}

export type AdminDataViewPatch = Omit<Partial<AdminDataViewInput>, "source">;

/** A page of source rows, shaped alike across the three public endpoints. */
export interface DataViewRowPage {
  items: Array<Record<string, unknown>>;
  /** `null` when the source cannot report a total (mutant lines, variants). */
  total: number | null;
  nextCursor: string | null;
  hasMore: boolean;
}

export function listDataViewSources(): Promise<{ items: DataViewSourceInfo[] }> {
  return http.get("/admin/data-views/sources");
}

export function listAdminDataViews(
  params: { source?: DataViewSource } = {},
): Promise<{ items: AdminDataView[]; total: number }> {
  return http.get("/admin/data-views", {
    params: params.source ? { source: params.source } : undefined,
  });
}

export function createAdminDataView(body: AdminDataViewInput): Promise<AdminDataView> {
  return http.post("/admin/data-views", { json: body });
}

export function updateAdminDataView(
  viewId: number,
  body: AdminDataViewPatch,
): Promise<AdminDataView> {
  return http.put(`/admin/data-views/${viewId}`, { json: body });
}

export function deleteAdminDataView(viewId: number): Promise<void> {
  return http.delete(`/admin/data-views/${viewId}`);
}

const INTEGER_FILTERS: Record<DataViewSource, ReadonlySet<string>> = {
  genes: new Set(["start_pos", "end_pos"]),
  variants: new Set(["start", "end", "min_af", "max_af"]),
  mutant_lines: new Set(),
};

/** Coerce stored filter strings back to the types the public API expects. */
export function buildSourceFilters(
  view: Pick<AdminDataView, "source" | "filters">,
): Record<string, string | number> {
  const integers = INTEGER_FILTERS[view.source];
  const params: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(view.filters)) {
    const text = value.trim();
    if (!text) continue;
    params[key] = integers.has(key) ? Number(text) : text;
  }
  return params;
}

function sortRows(
  rows: Array<Record<string, unknown>>,
  field: string | null,
  direction: DataViewSortDir | null,
): Array<Record<string, unknown>> {
  if (!field || !direction) return rows;
  const factor = direction === "asc" ? 1 : -1;
  return [...rows].sort((left, right) => {
    const a = left[field];
    const b = right[field];
    if (a === b) return 0;
    if (a === null || a === undefined) return 1;
    if (b === null || b === undefined) return -1;
    if (typeof a === "number" && typeof b === "number") return (a - b) * factor;
    return String(a).localeCompare(String(b)) * factor;
  });
}

/**
 * Fetch one page of rows for a saved view.
 *
 * Genes page server-side and accept a sort; variants and mutant lines are
 * cursor/offset paginated, so their sort is applied to the loaded page only.
 */
export async function fetchDataViewRows(
  view: AdminDataView,
  options: { page?: number; cursor?: string | null } = {},
): Promise<DataViewRowPage> {
  const pageSize = view.page_size;
  const filters = buildSourceFilters(view);

  if (view.source === "genes") {
    const page = Math.max(1, options.page ?? 1);
    const response = await searchGenes({
      ...filters,
      page,
      page_size: pageSize,
      sort_by: view.sort_field ?? undefined,
      sort_dir: view.sort_field ? view.sort_dir ?? undefined : undefined,
    });
    return {
      items: response.items as unknown as Array<Record<string, unknown>>,
      total: response.total,
      nextCursor: null,
      hasMore: response.has_more,
    };
  }

  if (view.source === "variants") {
    const response = await searchVariants({
      ...filters,
      limit: pageSize,
      cursor: options.cursor ?? undefined,
    });
    return {
      items: sortRows(
        response.items as unknown as Array<Record<string, unknown>>,
        view.sort_field,
        view.sort_dir,
      ),
      total: response.total_count,
      nextCursor: response.next_cursor,
      hasMore: response.has_more,
    };
  }

  const page = Math.max(1, options.page ?? 1);
  const rows = await listMutantLines({
    ...filters,
    offset: (page - 1) * pageSize,
    limit: pageSize,
  });
  return {
    items: sortRows(
      rows as unknown as Array<Record<string, unknown>>,
      view.sort_field,
      view.sort_dir,
    ),
    total: null,
    nextCursor: null,
    hasMore: rows.length === pageSize,
  };
}