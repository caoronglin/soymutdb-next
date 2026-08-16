/**
 * Sequenced default PageDefinitions (Phase 4 seed).
 *
 * Encodes the approved seven-page reference layout
 * (docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md)
 * as data. The public renderer consumes these until the backend PageBuilder
 * (Phase 2) serves real published definitions; the shape is identical so the
 * swap is drop-in.
 *
 * The five-item primary navigation order is fixed:
 *   Home / Search / Tools / Latest News / Contact.
 */

import type { PageDefinition, PageComponent } from "./types";

/** Fixed primary navigation order (single source of truth for header/footer). */
export const NAVIGATION_ORDER = [
  { to: "/", labelKey: "nav.home" },
  { to: "/search", labelKey: "nav.search" },
  { to: "/tools", labelKey: "nav.tools" },
  { to: "/news", labelKey: "nav.latestNews" },
  { to: "/help", labelKey: "nav.contact" },
] as const;

/** The five home tool entries, in the approved order. */
export const HOME_TOOL_ENTRIES: ReadonlyArray<PageComponent> = [
  {
    type: "tool-entry",
    id: "tool-gene-id",
    props: {
      target: "gene-id",
      labelKey: "home.taskGeneId",
      descriptionKey: "search.genes.subtitle",
    },
  },
  {
    type: "tool-entry",
    id: "tool-physical-location",
    props: {
      target: "physical-location",
      labelKey: "home.taskLocation",
      descriptionKey: "search.location.subtitle",
    },
  },
  {
    type: "tool-entry",
    id: "tool-jbrowse-2",
    props: {
      target: "jbrowse-2",
      labelKey: "home.taskJbrowse",
      descriptionKey: "browser.subtitle",
    },
  },
  {
    type: "tool-entry",
    id: "tool-blast",
    props: {
      target: "blast",
      labelKey: "home.taskBlast",
      descriptionKey: "blast.subtitle",
    },
  },
  {
    type: "tool-entry",
    id: "tool-primer-design",
    props: {
      target: "primer-design",
      labelKey: "home.taskPrimer",
      descriptionKey: "search.primer.subtitle",
    },
  },
];

/** Home page: 2:3 news/carousel grid + five tool entries + CMS content. */
export const HOME_DEFINITION: PageDefinition = {
  schema_version: 1,
  route: "/",
  labelKey: "nav.home",
  sections: [
    {
      id: "home-top",
      components: [
        {
          type: "columns",
          id: "home-news-carousel",
          props: {
            ratio: "2fr_3fr",
            children: [
              { type: "latest-news", id: "home-latest-news", props: { max: 5 } },
              {
                type: "featured-carousel",
                id: "home-featured-carousel",
                props: { minSlides: 3, maxSlides: 6 },
              },
            ],
          },
        },
      ],
    },
    {
      id: "home-tools",
      components: HOME_TOOL_ENTRIES.slice(),
    },
    {
      id: "home-content",
      components: [{ type: "rich-text", id: "home-cms", props: { contentKey: "home.welcome" } }],
    },
  ],
};

/** Seed definitions for the public pages driven by the renderer. */
export const DEFAULT_PAGE_DEFINITIONS: ReadonlyArray<PageDefinition> = [HOME_DEFINITION];

/** Fallback navigation used when no definition/API is available. */
export function defaultNavigation(): ReadonlyArray<{ to: string; labelKey: string }> {
  return NAVIGATION_ORDER;
}
