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

/** Component renderer keys owned by the server registry. */
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
  | "blast_launcher"
  | "ontology_relationship_graph";

export interface PageComponentNode {
  type: PageComponentType;
  props: Record<string, unknown>;
  children?: PageComponentNode[];
}

export type PageDefinitionTheme =
  | "scientific-light"
  | "scientific-dark"
  | "high-contrast"
  | "compact-data"
  | "print";

export interface PageDefinitionDataSource {
  id: string;
  kind: string;
  dataset_version_id?: string;
  config?: Record<string, unknown>;
}

export interface PageDefinitionLayouts {
  desktop: Record<string, unknown>;
  tablet: Record<string, unknown>;
  mobile: Record<string, unknown>;
}

/** Legacy payload produced before schema versioning was introduced. */
export interface PageDefinitionV1 {
  schema_version?: never;
  title_key?: string;
  root: PageComponentNode;
}

/** Current normalized page-definition contract. */
export interface PageDefinitionV2 {
  schema_version: 2;
  title_key?: string;
  root: PageComponentNode;
  data_sources: PageDefinitionDataSource[];
  theme_id: PageDefinitionTheme;
  layouts: PageDefinitionLayouts;
}

/** Wire payload accepted while persisted v1 definitions are upgraded lazily. */
export type CompatiblePageDefinition = PageDefinitionV1 | PageDefinitionV2;

/** Page-definition payload returned by versioned APIs during the v1/v2 rollout. */
export type PageDefinition = CompatiblePageDefinition;

const PAGE_THEMES: ReadonlySet<string> = new Set([
  "scientific-light",
  "scientific-dark",
  "high-contrast",
  "compact-data",
  "print",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** True when a value has the shape required for a component-tree node. */
export function isPageComponentNode(value: unknown): value is PageComponentNode {
  return isRecord(value) && typeof value.type === "string" && isRecord(value.props);
}

function normalizeDataSources(value: unknown): PageDefinitionDataSource[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry) => {
    if (!isRecord(entry) || typeof entry.id !== "string" || typeof entry.kind !== "string") {
      return [];
    }
    return [{
      id: entry.id,
      kind: entry.kind,
      ...(typeof entry.dataset_version_id === "string"
        ? { dataset_version_id: entry.dataset_version_id }
        : {}),
      ...(isRecord(entry.config) ? { config: entry.config } : {}),
    }];
  });
}

/** Upgrade a valid v1/v2 wire payload to the current renderer/editor contract. */
export function normalizePageDefinition(value: unknown): PageDefinitionV2 | null {
  if (!isRecord(value) || !isPageComponentNode(value.root)) return null;
  if (value.schema_version !== undefined && value.schema_version !== 2) return null;

  const layouts = isRecord(value.layouts) ? value.layouts : {};
  const theme = PAGE_THEMES.has(String(value.theme_id))
    ? (value.theme_id as PageDefinitionTheme)
    : "scientific-light";

  return {
    schema_version: 2,
    ...(typeof value.title_key === "string" ? { title_key: value.title_key } : {}),
    root: value.root,
    data_sources: normalizeDataSources(value.data_sources),
    theme_id: theme,
    layouts: {
      desktop: isRecord(layouts.desktop) ? layouts.desktop : {},
      tablet: isRecord(layouts.tablet) ? layouts.tablet : {},
      mobile: isRecord(layouts.mobile) ? layouts.mobile : {},
    },
  };
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
