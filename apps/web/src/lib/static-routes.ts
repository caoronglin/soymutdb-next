/**
 * Static-route enumeration shared by the build script and its tests.
 *
 * The Vue portal is a data-driven SPA; static hosting still needs a real
 * document per stable route so crawlers and no-JS clients get a titled page
 * instead of a fallback shell. This module derives that document set from the
 * route metadata, renders the sitemap/robots policy, and injects per-page head
 * tags. It is dependency-free so `tsx` can run it outside Vite.
 */

import type { PortalRouteMeta } from "../router/routes";

export interface RouteLike {
  path: string;
  meta?: Partial<PortalRouteMeta>;
}

export interface StaticRouteEntry {
  /** Router path, e.g. "/search". */
  path: string;
  title: string;
  description?: string;
  includeInSitemap: boolean;
}

export type SiteVariant = "external" | "internal";

/**
 * Routes that get their own `index.html`. Dynamic segments are skipped even if
 * metadata marks them prerenderable — a template path is not a document.
 */
export function deriveStaticRouteEntries(
  routes: readonly RouteLike[],
  siteVariant: SiteVariant,
): StaticRouteEntry[] {
  return routes
    .filter((route) => route.meta?.prerender === true && !route.path.includes(":"))
    .map((route) => ({
      path: route.path,
      title: String(route.meta?.title ?? "SoyMutDB"),
      description: route.meta?.description ? String(route.meta.description) : undefined,
      // The internal site variant is never listed for indexing.
      includeInSitemap: siteVariant === "external" && route.meta?.sitemap === true,
    }))
    .sort((left, right) => left.path.localeCompare(right.path));
}

/** "/search" -> "search/index.html"; "/" -> "index.html". */
export function directoryIndexPath(path: string): string {
  const trimmed = path.replace(/^\/+|\/+$/g, "");
  return trimmed ? `${trimmed}/index.html` : "index.html";
}

const HTML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => HTML_ESCAPES[character]);
}

/** Replace `<title>` and append page metadata before `</head>`. */
export function injectPageHead(
  html: string,
  entry: StaticRouteEntry,
  origin?: string,
  siteVariant: SiteVariant = "external",
): string {
  const withTitle = html.replace(
    /<title>[\s\S]*?<\/title>/,
    `<title>${escapeHtml(entry.title)}</title>`,
  );
  const tags: string[] = [];
  if (entry.description) {
    tags.push(`<meta name="description" content="${escapeHtml(entry.description)}" />`);
  }
  if (origin) {
    tags.push(`<link rel="canonical" href="${escapeHtml(new URL(entry.path, origin).toString())}" />`);
  }
  let document = withTitle;
  if (siteVariant === "internal") {
    // The Umi document shell may already carry a robots meta from the app
    // config. Duplicating it is invalid head markup (and a strict-mode trap
    // for tests), so upgrade the existing tag to the full policy instead of
    // appending a second one.
    const fullPolicy = '<meta name="robots" content="noindex, nofollow, noarchive" />';
    if (/<meta name="robots"/i.test(document)) {
      document = document.replace(/<meta name="robots"[^>]*>/i, fullPolicy);
    } else {
      tags.push(fullPolicy);
    }
  }
  if (tags.length === 0) return document;
  return document.replace("</head>", `  ${tags.join("\n    ")}\n  </head>`);
}

export function renderSitemap(entries: readonly StaticRouteEntry[], origin: string): string {
  const urls = entries
    .filter((entry) => entry.includeInSitemap)
    .map(
      (entry) =>
        `  <url><loc>${escapeHtml(new URL(entry.path, origin).toString())}</loc></url>`,
    )
    .join("\n");
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    urls,
    "</urlset>",
    "",
  ].join("\n");
}

export function renderRobots(siteVariant: SiteVariant, origin?: string): string {
  if (siteVariant === "internal") {
    return "User-agent: *\nDisallow: /\n";
  }
  const lines = ["User-agent: *", "Allow: /"];
  if (origin) {
    lines.push(`Sitemap: ${new URL("/sitemap.xml", origin).toString()}`);
  }
  return `${lines.join("\n")}\n`;
}
