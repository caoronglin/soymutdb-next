/**
 * Immutable fallback PageDefinitions (Phase 8).
 *
 * These mirror `apps/api/app/scripts/seed_page_builder.py` exactly (the same
 * snake_case renderer keys, `{ title_key, root }` shape, 5-entry navigation,
 * 7 reference pages). They are used ONLY as the offline / API-failure fallback
 * — never as the source of truth once a published definition is available.
 *
 * The primary navigation order is fixed:
 *   Home / Search / Tools / Latest News / Contact.
 */

import type { PageDefinition } from "@soymutdb/shared";

/**
 * Fixed primary navigation order (single source of truth for the header).
 * Routes point at the app's real React routes in the approved IA order
 * (Home / Search / Tools / Latest News / Contact). The backend seed is
 * aligned to the same target routes (`/news`, `/help`).
 */
export const NAVIGATION_ORDER = [
  { label: "Home", route: "/" },
  { label: "Search", route: "/search" },
  { label: "Tools", route: "/tools" },
  { label: "Latest News", route: "/news" },
  { label: "Contact", route: "/help" },
] as const;

/** Five direct task-entry labels, in the approved reference order. */
export const TOOL_ENTRY_LABELS = [
  "Gene ID",
  "Physical Location",
  "JBrowse 2",
  "BLAST",
  "Primer Design",
] as const;

/** Six-column result order shared by Gene ID and Location search. */
export const RESULT_COLUMNS = [
  "Assembly",
  "Chromosome",
  "Position",
  "Mutation Feature",
  "Gene ID",
  "JBrowse 2",
] as const;

function navigationNode(): PageDefinition["root"] {
  return {
    type: "navigation",
    props: {
      title: "Site Navigation",
      items: NAVIGATION_ORDER.map((i) => ({ label: i.label, route: i.route })),
    },
  };
}

/** Home (`/`) reference definition. */
export const HOME_DEFINITION: PageDefinition = {
  title_key: "nav.home",
  root: {
    type: "columns",
    props: { columns: 1 },
    children: [
      navigationNode(),
      {
        type: "tool_entries",
        props: { entries: [...TOOL_ENTRY_LABELS] },
      },
      { type: "news_list", props: { limit: 5 } },
      // Featured carousel (news-driven) — mirrors the backend home seed.
      { type: "media_carousel", props: { items: [] } },
      {
        type: "resource_cards",
        props: {
          heading: "资源导览",
          cards: [
            { title: "数据下载", description: "下载参考基因组、变异与注释数据", href: "/downloads" },
            { title: "使用指南", description: "快速上手与检索帮助", href: "/guide" },
            { title: "文献 / 出版物", description: "SoyMutDB 相关文献", href: "/publications" },
          ],
        },
      },
      { type: "rich_text", props: { content: "<p>SoyMutDB home content</p>" } },
    ],
  },
};

/**
 * Fallback definitions for the routes driven by the renderer. The list mirrors
 * the seeded pages, minus the specialized JBrowse 2 / BLAST launcher routes
 * (served by dedicated code) and the search result routes (form + table).
 */
export const FALLBACK_DEFINITIONS: ReadonlyArray<PageDefinition> = [HOME_DEFINITION];

/**
 * Resolve a fallback definition for a route, or null when none is seeded.
 * Used by the loader when the API is unavailable or the route is unknown.
 */
export function fallbackDefinitionFor(route: string): PageDefinition | null {
  if (route === "/" || route === "") return HOME_DEFINITION;
  return null;
}

/** The default (immutable) navigation, used when no definition is available. */
export function defaultNavigation(): ReadonlyArray<{ label: string; route: string }> {
  return NAVIGATION_ORDER;
}
