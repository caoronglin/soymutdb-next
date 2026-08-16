/**
 * Shared Page Builder DTOs (isomorphic with the server registry).
 *
 * These types mirror `apps/api/app/page_builder/schemas.py` and the component
 * registry renderer keys so the public renderer, the Admin editor, and the SSG
 * pipeline share one definition contract.  Keep ``renderer_key`` values in
 * exact sync with `apps/api/app/page_builder/registry.py`.
 */

export type PageDefinitionStatus =
  | "draft"
  | "preview"
  | "requested"
  | "published";

/** Component renderer keys owned by the server registry (16 types). */
export type PageComponentType =
  | "navigation"
  | "news_list"
  | "media_carousel"
  | "rich_text"
  | "tool_entries"
  | "assembly_select"
  | "gene_search_form"
  | "location_search_form"
  | "data_table"
  | "button"
  | "link"
  | "notice"
  | "divider"
  | "tabs"
  | "columns"
  | "jbrowse_launcher"
  | "blast_launcher";

export interface PageComponentNode {
  type: PageComponentType;
  props: Record<string, unknown>;
  children?: PageComponentNode[];
}

export interface PageDefinition {
  title_key?: string;
  root: PageComponentNode;
}

export interface PageDefinitionSummary {
  id: string;
  route: string;
  title_key: string;
  latest_version: number;
  latest_status: PageDefinitionStatus;
  created_at: string;
  updated_at: string;
}

export interface PageDefinitionVersion {
  id: string;
  page_id: string;
  version: number;
  status: PageDefinitionStatus;
  definition: PageDefinition;
  edited_by: string | null;
  edit_comment: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PageDefinitionResponse {
  id: string;
  route: string;
  title_key: string;
  versions: PageDefinitionVersion[];
  created_at: string;
  updated_at: string;
}

export interface PageDefinitionListResponse {
  items: PageDefinitionSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface ComponentDescriptor {
  renderer_key: PageComponentType;
  label: string;
  config_schema: Record<string, unknown>;
  allowed_children: string[];
}

export interface RegistryResponse {
  components: ComponentDescriptor[];
}
