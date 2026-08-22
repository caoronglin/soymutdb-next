/**
 * Public page-builder types (Phase 8) — aligned with the shared server DTO.
 *
 * The single source of truth is `packages/shared/src/page-builder.ts`, which
 * mirrors `apps/api/app/page_builder/{schemas,registry}.py`. The public renderer
 * consumes that exact contract (snake_case renderer keys, `{ title_key, root }`
 * definition shape) so a published definition can flow Admin → API → SSG
 * bootstrap → renderer without re-mapping.
 *
 * Security invariant (enforced server-side by the registry, re-checked here as
 * defence in depth): a PageDefinition carries NO executable JavaScript, NO
 * arbitrary templates, and NO raw HTML. The only component that renders
 * arbitrary HTML is `rich_text`, and its content passes through DOMPurify.
 */

export type {
  PageDefinitionStatus,
  PageComponentType,
  PageComponentNode,
  PageDefinitionTheme,
  PageDefinitionDataSource,
  PageDefinitionLayouts,
  PageDefinitionV1,
  PageDefinitionV2,
  CompatiblePageDefinition,
  PageDefinition,
  PageDefinitionSummary,
  PageDefinitionVersion,
  PageDefinitionResponse,
  PageDefinitionListResponse,
  ComponentDescriptor,
  RegistryResponse,
} from "@soymutdb/shared";
export {
  isPageComponentNode,
  normalizePageDefinition,
} from "@soymutdb/shared";

import {
  normalizePageDefinition,
  type PageDefinition,
} from "@soymutdb/shared";

/** Renderer keys owned by the server registry, in registry order. */
export const COMPONENT_TYPE_KEYS = [
  "navigation",
  "news_list",
  "media_carousel",
  "rich_text",
  "tool_entries",
  "assembly_select",
  "gene_search_form",
  "location_search_form",
  "data_table",
  "button",
  "link",
  "notice",
  "divider",
  "tabs",
  "columns",
  "jbrowse_launcher",
  "blast_launcher",
  "ontology_relationship_graph",
] as const;

export type ComponentTypeKey = (typeof COMPONENT_TYPE_KEYS)[number];

/** True when a string is an allowlisted component renderer key. */
export function isComponentTypeKey(value: unknown): value is ComponentTypeKey {
  return typeof value === "string" && (COMPONENT_TYPE_KEYS as readonly string[]).includes(value);
}

/** Reject script-like values before they can reach the DOM. */
export function isScriptLike(value: unknown): boolean {
  return /javascript\s*:/i.test(String(value));
}

/** True when `value` looks like a full page definition (has a `root`). */
export function isPageDefinition(value: unknown): value is PageDefinition {
  return normalizePageDefinition(value) !== null;
}
