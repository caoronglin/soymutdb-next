/**
 * Public page-builder type definitions (Phase 4).
 *
 * These describe the safe, data-only PageDefinition consumed by the public
 * renderer. They intentionally mirror the server-owned registry allowlist
 * (docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md)
 * but live on the frontend so the static renderer has zero dependency on the
 * backend PageBuilder introduced in Phase 2.
 *
 * Security invariant: a PageDefinition carries NO executable JavaScript, NO
 * arbitrary templates, and NO raw HTML. The only component that renders
 * arbitrary HTML is `rich-text`, and its content must pass through the
 * existing DOMPurify pipeline in the adapter.
 */

/** Route metadata + translated labels + SEO fields. */
export interface PageRouteMeta {
  path: string;
  /** i18next keys (not raw strings) resolved by the caller. */
  titleKey: string;
  descriptionKey: string;
  seo?: {
    titleKey?: string;
    descriptionKey?: string;
  };
}

/**
 * Discriminated union of every public component a PageDefinition may use.
 * Unknown `type` values are rejected before reaching the DOM in production.
 */
export type PageComponent =
  | { type: "site-navigation"; id: string }
  | { type: "footer-navigation"; id: string }
  | { type: "latest-news"; id: string; props?: { max?: number } }
  | { type: "featured-carousel"; id: string; props?: { minSlides?: number; maxSlides?: number } }
  | { type: "rich-text"; id: string; props: { contentKey?: string; html?: string } }
  | { type: "tool-entry"; id: string; props: ToolEntryProps }
  | { type: "assembly-selector"; id: string; props?: Record<string, never> }
  | { type: "gene-query-form"; id: string; props?: Record<string, never> }
  | { type: "location-query-form"; id: string; props?: Record<string, never> }
  | { type: "data-table"; id: string; props?: DataTableProps }
  | { type: "button"; id: string; props: ButtonProps }
  | { type: "link"; id: string; props: LinkProps }
  | { type: "notice"; id: string; props: NoticeProps }
  | { type: "divider"; id: string; props?: Record<string, never> }
  | { type: "tabs"; id: string; props?: TabsProps }
  | { type: "columns"; id: string; props: ColumnsProps }
  | { type: "jbrowse-launcher"; id: string; props?: Record<string, never> }
  | { type: "blast-launcher"; id: string; props?: Record<string, never> };

/** The five approved task-entry tools, in fixed order. */
export type ToolEntryKind =
  | "gene-id"
  | "physical-location"
  | "jbrowse-2"
  | "blast"
  | "primer-design";

export interface ToolEntryProps {
  target: ToolEntryKind;
  /** i18next keys for label / description. */
  labelKey: string;
  descriptionKey: string;
}

export interface ButtonProps {
  labelKey: string;
  /** Approved interaction: navigate (same tab) or a whitelisted target. */
  action: "navigate" | "new-tab";
  to: string;
}

export interface LinkProps {
  labelKey: string;
  to: string;
  newTab?: boolean;
}

export interface NoticeProps {
  kind: "info" | "warning" | "error";
  textKey: string;
}

export interface TabsProps {
  /** i18next keys for each tab label. */
  tabs: ReadonlyArray<{ labelKey: string; id: string }>;
}

export interface ColumnsProps {
  /** CSS grid ratio, e.g. "2fr_3fr" encodes the 2:3 home split. */
  ratio?: "1fr" | "1fr_1fr" | "2fr_3fr" | "3fr_2fr";
  children: PageComponent[];
}

export interface DataTableProps {
  /** Approved column order — refer to registry column descriptors. */
  columns?: ReadonlyArray<string>;
}

/** Ordered section of a page — a responsive columns row or a set of modules. */
export interface PageSection {
  id: string;
  /** Ordered list of component nodes to render. */
  components: PageComponent[];
}

/** A single published (or draft) page definition. */
export interface PageDefinition {
  schema_version: number;
  /** Full route path, e.g. "/" or "/search/genes". */
  route: string;
  labelKey: string;
  sections: PageSection[];
}

export const PAGE_SCHEMA_VERSION = 1;

/** Recognised component type keys (source of truth for the renderer map). */
export const COMPONENT_TYPE_KEYS = [
  "site-navigation",
  "footer-navigation",
  "latest-news",
  "featured-carousel",
  "rich-text",
  "tool-entry",
  "assembly-selector",
  "gene-query-form",
  "location-query-form",
  "data-table",
  "button",
  "link",
  "notice",
  "divider",
  "tabs",
  "columns",
  "jbrowse-launcher",
  "blast-launcher",
] as const;

export type ComponentTypeKey = (typeof COMPONENT_TYPE_KEYS)[number];

export function isComponentTypeKey(value: unknown): value is ComponentTypeKey {
  return typeof value === "string" && (COMPONENT_TYPE_KEYS as readonly string[]).includes(value);
}

/**
 * Reject script-like props/actions before they can reach the DOM.
 * Called by the renderer for every node; returns true when the node is safe.
 */
export function isScriptLike(value: unknown): boolean {
  return /javascript\s*:/i.test(String(value));
}
