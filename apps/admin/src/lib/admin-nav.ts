/**
 * Admin sidebar navigation — the console's information architecture.
 *
 * This is deliberately a hand-written tree rather than a projection of the
 * router: the route table also carries redirects, deep links and retired
 * ADR-0009 placeholders, and mapping it 1:1 would put a nav entry next to every
 * implementation detail. The React console kept the same split (`NAV_SECTIONS`
 * beside the route tree); the Vue port had collapsed it into "every route with a
 * `navKey`", which is why several reachable pages had no entry at all.
 *
 * Section and item labels fall back to an English default because the shared
 * `@soymutdb/i18n-core` catalog does not yet carry the `admin.shell.*` keys the
 * React console referenced with the same fallback.
 */

/** Inline SVG path data — no icon dependency, no runtime component lookup. */
export interface AdminNavItem {
  path: string;
  labelKey: string;
  labelDefault: string;
  /** One or more `d` attributes drawn in a 24×24 viewBox. */
  icon: readonly string[];
}

export interface AdminNavSection {
  labelKey: string;
  labelDefault: string;
  items: readonly AdminNavItem[];
}

export const ADMIN_NAV_SECTIONS: readonly AdminNavSection[] = [
  {
    labelKey: "admin.shell.overview",
    labelDefault: "Overview",
    items: [
      {
        path: "/",
        labelKey: "admin.dashboard.title",
        labelDefault: "Dashboard",
        icon: ["M4 13h6V4H4v9Zm10 7h6v-9h-6v9ZM4 20h6v-4H4v4Zm10-11h6V4h-6v5Z"],
      },
    ],
  },
  {
    labelKey: "admin.shell.dataManagement",
    labelDefault: "Data Management",
    items: [
      {
        path: "/releases",
        labelKey: "admin.releases",
        labelDefault: "Releases",
        icon: [
          "M12 3v18",
          "M5 8.5 12 5l7 3.5-7 3.5-7-3.5Z",
          "M5 15.5 12 19l7-3.5",
        ],
      },
      {
        path: "/imports",
        labelKey: "admin.imports",
        labelDefault: "Data Imports",
        icon: ["M12 16V5", "m7.5 9.5 4.5-4.5 4.5 4.5", "M5 15v3.5h14V15"],
      },
      {
        path: "/table-templates",
        labelKey: "admin.tableViews",
        labelDefault: "Table Views",
        icon: ["M4 6h16", "M4 12h16", "M4 18h16", "M9 6v12"],
      },
      {
        path: "/instances",
        labelKey: "admin.instances.title",
        labelDefault: "Species Instances",
        icon: [
          "M4 7c0-1.66 3.58-3 8-3s8 1.34 8 3-3.58 3-8 3-8-1.34-8-3Z",
          "M4 7v10c0 1.66 3.58 3 8 3s8-1.34 8-3V7",
          "M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3",
        ],
      },
      {
        path: "/resource-catalog",
        labelKey: "admin.shell.resourceCatalog",
        labelDefault: "Resource Catalog",
        icon: ["M4 7.5A2.5 2.5 0 0 1 6.5 5H10l2 2.5h5.5A2.5 2.5 0 0 1 20 10v6.5a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5v-9Z"],
      },
    ],
  },
  {
    labelKey: "admin.shell.content",
    labelDefault: "Content",
    items: [
      {
        path: "/content/pages",
        labelKey: "admin.contentPages.title",
        labelDefault: "Pages",
        icon: ["M7 4h7l5 5v11H7V4Z", "M14 4v5h5", "M10 13h6", "M10 16.5h4"],
      },
      {
        path: "/content/legacy",
        labelKey: "admin.contentLegacy.title",
        labelDefault: "Legacy Pages",
        icon: ["M6 4h9l4 4v12H6V4Z", "M15 4v4h4", "M9.5 14.5 12 17l3-3.5"],
      },
      {
        path: "/news",
        labelKey: "admin.news.title",
        labelDefault: "News",
        icon: ["M5 5h11v14H5z", "M16 9h3v8.5A1.5 1.5 0 0 1 16 19", "M8 9h5", "M8 12.5h5", "M8 16h3"],
      },
      {
        path: "/publications",
        labelKey: "publications.title",
        labelDefault: "Publications",
        icon: ["M6 4h12v16l-3-2-3 2-3-2-3 2V4Z", "M9.5 9h5", "M9.5 12.5h5"],
      },
      {
        path: "/media",
        labelKey: "admin.shell.media",
        labelDefault: "Media Library",
        icon: ["M4.5 5.5h15v13h-15z", "m6.5 16 4-4.5 3 3 2.5-2.5 1.5 4", "M9.5 9.5h.01"],
      },
    ],
  },
  {
    labelKey: "admin.shell.presentation",
    labelDefault: "Presentation",
    items: [
      {
        path: "/widgets",
        labelKey: "admin.shell.widgets",
        labelDefault: "Widgets",
        icon: ["M4.5 4.5h6v6h-6z", "M13.5 4.5h6v6h-6z", "M4.5 13.5h6v6h-6z", "M13.5 13.5h6v6h-6z"],
      },
      {
        path: "/layout",
        labelKey: "admin.shell.layoutEditor",
        labelDefault: "Layout Editor",
        icon: ["M4.5 5.5h15v13h-15z", "M4.5 10h15", "M10.5 10v8.5"],
      },
      {
        path: "/widget-preview",
        labelKey: "admin.shell.widgetPreview",
        labelDefault: "Widget Preview",
        icon: ["M2.5 12S6 6.5 12 6.5 21.5 12 21.5 12 18 17.5 12 17.5 2.5 12 2.5 12Z", "M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z"],
      },
      {
        path: "/widget-health",
        labelKey: "admin.shell.widgetHealth",
        labelDefault: "Widget Health",
        icon: ["M4 17.5 8.5 12l3 3L20 6", "M4 20h16"],
      },
    ],
  },
  {
    labelKey: "admin.shell.administration",
    labelDefault: "Administration",
    items: [
      {
        path: "/audit",
        labelKey: "admin.auditLogs",
        labelDefault: "Audit Logs",
        icon: ["M6 4h9l4 4v12H6V4Z", "M15 4v4h4", "M9.5 12.5h5", "M9.5 16h3"],
      },
      {
        path: "/settings",
        labelKey: "admin.settings",
        labelDefault: "Settings",
        icon: [
          "M12 9.25a2.75 2.75 0 1 0 0 5.5 2.75 2.75 0 0 0 0-5.5Z",
          "M19.4 13.5a7.6 7.6 0 0 0 0-3l1.6-1.2-1.7-3-1.9.8a7.6 7.6 0 0 0-2.6-1.5L14.5 3h-3.4l-.3 2.6a7.6 7.6 0 0 0-2.6 1.5l-1.9-.8-1.7 3L6.2 10.5a7.6 7.6 0 0 0 0 3L4.6 14.7l1.7 3 1.9-.8a7.6 7.6 0 0 0 2.6 1.5l.3 2.6h3.4l.3-2.6a7.6 7.6 0 0 0 2.6-1.5l1.9.8 1.7-3-1.6-1.2Z",
        ],
      },
      {
        path: "/features",
        labelKey: "admin.features",
        labelDefault: "Feature Flags",
        icon: ["m5 12.5 4 4 10-10"],
      },
      {
        path: "/analytics-settings",
        labelKey: "admin.analyticsSettings.title",
        labelDefault: "Analytics",
        icon: ["M5 19V9", "M12 19V5", "M19 19v-6", "M3.5 19h17"],
      },
    ],
  },
];

/**
 * Page titles for the top bar, keyed by exact path or longest matching prefix.
 * Mirrors the React `PAGE_TITLES` map so the header names the current page
 * instead of repeating the console name on every route.
 */
export const ADMIN_PAGE_TITLES: readonly { path: string; labelKey: string; labelDefault: string }[] = [
  { path: "/", labelKey: "admin.dashboard.title", labelDefault: "Dashboard" },
  { path: "/releases", labelKey: "admin.releases", labelDefault: "Releases" },
  { path: "/imports", labelKey: "admin.imports", labelDefault: "Data Imports" },
  { path: "/table-templates", labelKey: "admin.tableViews", labelDefault: "Table Views" },
  { path: "/instances", labelKey: "admin.instances.title", labelDefault: "Species Instances" },
  { path: "/resource-catalog", labelKey: "admin.shell.resourceCatalog", labelDefault: "Resource Catalog" },
  { path: "/content", labelKey: "admin.content", labelDefault: "Content Management" },
  { path: "/publications", labelKey: "publications.title", labelDefault: "Publications" },
  { path: "/news", labelKey: "admin.news.title", labelDefault: "News Management" },
  { path: "/media", labelKey: "admin.shell.media", labelDefault: "Media Library" },
  { path: "/widgets", labelKey: "admin.shell.widgets", labelDefault: "Widgets" },
  { path: "/layout", labelKey: "admin.shell.layoutEditor", labelDefault: "Layout Editor" },
  { path: "/widget-preview", labelKey: "admin.shell.widgetPreview", labelDefault: "Widget Preview" },
  { path: "/widget-health", labelKey: "admin.shell.widgetHealth", labelDefault: "Widget Health" },
  { path: "/audit", labelKey: "admin.auditLogs", labelDefault: "Audit Logs" },
  { path: "/settings", labelKey: "admin.settings", labelDefault: "System Settings" },
  { path: "/analytics-settings", labelKey: "admin.analyticsSettings.title", labelDefault: "Analytics" },
  { path: "/features", labelKey: "admin.features", labelDefault: "Feature Flags" },
];

/**
 * Resolve the title for a pathname: exact match first, then the longest
 * matching prefix, so `/widgets/foo` still names "Widgets" rather than falling
 * back to the bare console name.
 */
export function adminTitleFor(pathname: string): { labelKey: string; labelDefault: string } | null {
  const exact = ADMIN_PAGE_TITLES.find((entry) => entry.path === pathname);
  if (exact) return exact;
  return (
    ADMIN_PAGE_TITLES.filter(
      (entry) => entry.path !== "/" && pathname.startsWith(`${entry.path}/`),
    ).sort((a, b) => b.path.length - a.path.length)[0] ?? null
  );
}
