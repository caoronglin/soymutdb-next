/**
 * Configurable table views (column templates).
 *
 * The portal asks the API which columns to render instead of hard-coding them,
 * so the admin console can reorder, relabel, hide or add columns — including
 * the cross-assembly homolog columns — without a frontend release.
 */
import { http } from "./auth";

export type TableKind = "mutation_sites" | "variants" | "genes" | "mutant_lines";

export const TABLE_KINDS: readonly TableKind[] = [
  "mutation_sites",
  "variants",
  "genes",
  "mutant_lines",
];

export interface TableColumn {
  key: string;
  label_zh: string;
  label_en: string;
  visible: boolean;
}

export interface TableActions {
  jbrowse: boolean;
  genome_preview: boolean;
}

export interface ResolvedTableView {
  kind: TableKind;
  species: string;
  site_variant: "external" | "internal";
  release_id: number | null;
  template_id: number | null;
  template_name: string;
  is_builtin_default: boolean;
  columns: TableColumn[];
  actions: TableActions;
}

export interface TableViewTemplate {
  id: number;
  kind: TableKind;
  name: string;
  species: string;
  site_variant: "external" | "internal";
  release_id: number | null;
  is_default: boolean;
  columns: TableColumn[];
  actions: TableActions;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface SpeciesInstance {
  id: number;
  code: string;
  name: string;
  species: string;
  api_base_url: string;
  jbrowse_base_url: string | null;
  portal_base_url: string | null;
  is_enabled: boolean;
  is_local: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface TableViewParams {
  species?: string;
  siteVariant?: "external" | "internal";
}

/** Resolve the ordered column layout for one portal table. */
export function getTableView(
  kind: TableKind,
  params: TableViewParams = {},
): Promise<ResolvedTableView> {
  const query: Record<string, string> = { species: params.species ?? "Glycine max" };
  if (params.siteVariant) query.variant = params.siteVariant;
  return http.get<ResolvedTableView>(`/table-views/${kind}`, { params: query });
}

export function listTableViewTemplates(params: {
  kind?: TableKind;
  species?: string;
} = {}): Promise<{ items: TableViewTemplate[]; total: number }> {
  const query: Record<string, string> = {};
  if (params.kind) query.kind = params.kind;
  if (params.species) query.species = params.species;
  return http.get(`/admin/table-views`, { params: query });
}

export function createTableViewTemplate(body: {
  kind: TableKind;
  name: string;
  species?: string;
  site_variant?: "external" | "internal";
  release_id?: number | null;
  is_default?: boolean;
  columns: TableColumn[];
  actions?: TableActions;
  notes?: string | null;
}): Promise<TableViewTemplate> {
  return http.post<TableViewTemplate>("/admin/table-views", { json: body });
}

export function updateTableViewTemplate(
  templateId: number,
  body: Partial<{
    name: string;
    columns: TableColumn[];
    actions: TableActions;
    is_default: boolean;
    release_id: number | null;
    notes: string | null;
  }>,
): Promise<TableViewTemplate> {
  return http.put<TableViewTemplate>(`/admin/table-views/${templateId}`, { json: body });
}

export function deleteTableViewTemplate(templateId: number): Promise<void> {
  return http.delete<void>(`/admin/table-views/${templateId}`);
}

export function listSpeciesInstances(): Promise<{ items: SpeciesInstance[]; total: number }> {
  return http.get<{ items: SpeciesInstance[]; total: number }>("/admin/species-instances");
}

export function createSpeciesInstance(body: {
  code: string;
  name: string;
  species: string;
  api_base_url: string;
  jbrowse_base_url?: string | null;
  portal_base_url?: string | null;
  is_enabled?: boolean;
  is_local?: boolean;
  notes?: string | null;
}): Promise<SpeciesInstance> {
  return http.post<SpeciesInstance>("/admin/species-instances", { json: body });
}

export function updateSpeciesInstance(
  instanceId: number,
  body: Partial<SpeciesInstance>,
): Promise<SpeciesInstance> {
  return http.put<SpeciesInstance>(`/admin/species-instances/${instanceId}`, { json: body });
}

export function deleteSpeciesInstance(instanceId: number): Promise<void> {
  return http.delete<void>(`/admin/species-instances/${instanceId}`);
}
