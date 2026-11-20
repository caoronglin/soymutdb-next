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
 * A document the build materialised from a *dynamic* route template.
 *
 * `/genes/:geneId` is not a document; `/genes/Glyma.01G000100.Wm82.a4.v1` is.
 * The caller has already decided which concrete paths exist (see
 * `lib/entity-snapshot.ts`, which derives them from the release snapshot), and
 * names the template each one was materialised from so eligibility stays a
 * property of the route table.
 */
export interface EntityRouteDocument {
  /** Concrete router path, e.g. "/genes/Glyma.01G000100.Wm82.a4.v1". */
  path: string;
  /** Template the path was materialised from, e.g. "/genes/:geneId". */
  templatePath: string;
  title: string;
  description?: string;
}

export interface DeriveStaticRouteOptions {
  /** Concrete documents the build's entity snapshot supplies. */
  entityDocuments?: readonly EntityRouteDocument[];
}

/**
 * Does a concrete path match a `:param` template, segment for segment?
 *
 * Counted, not prefix-matched: `:geneId` stands for exactly one non-empty
 * segment, so a snapshot entry can never address a path outside its template.
 */
function matchesTemplate(path: string, template: string): boolean {
  const actual = path.split("/");
  const expected = template.split("/");
  if (actual.length !== expected.length) return false;
  return expected.every((segment, index) => {
    const value = actual[index] ?? "";
    if (segment.startsWith(":")) {
      return value.length > 0 && value !== "." && value !== "..";
    }
    return segment === value;
  });
}

/**
 * Routes that get their own `index.html`.
 *
 * Stable routes come from the route metadata. A **dynamic** path (one with a
 * `:param` segment) is skipped unless the build's entity snapshot supplies that
 * concrete document: a template is not a document, and the data decides which
 * records the deployment publishes. No snapshot — the default — therefore emits
 * no entity document at all, and the artifact keeps the SPA shell for every
 * record page.
 */
export function deriveStaticRouteEntries(
  routes: readonly RouteLike[],
  siteVariant: SiteVariant,
  options: DeriveStaticRouteOptions = {},
): StaticRouteEntry[] {
  const entries: StaticRouteEntry[] = routes
    .filter((route) => route.meta?.prerender === true && !route.path.includes(":"))
    .map((route) => ({
      path: route.path,
      title: String(route.meta?.title ?? "SoyMutDB"),
      description: route.meta?.description ? String(route.meta.description) : undefined,
      // The internal site variant is never listed for indexing.
      includeInSitemap: siteVariant === "external" && route.meta?.sitemap === true,
    }));

  const seen = new Set(entries.map((entry) => entry.path));
  for (const document of options.entityDocuments ?? []) {
    // Eligibility is the route table's, not the snapshot's: a path whose
    // template is missing (or is not dynamic) is not a route this app serves.
    const template = routes.find((route) => route.path === document.templatePath);
    if (!template || !template.path.includes(":")) continue;
    if (!matchesTemplate(document.path, template.path)) continue;
    if (seen.has(document.path)) continue;
    seen.add(document.path);
    entries.push({
      path: document.path,
      title: document.title,
      description: document.description,
      // Released records are indexable on the external variant unless the
      // route metadata says otherwise; the internal variant never is.
      includeInSitemap: siteVariant === "external" && template.meta?.sitemap !== false,
    });
  }

  return entries.sort((left, right) => left.path.localeCompare(right.path));
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

/**
 * Body text for a document that is only a title around a JS app.
 *
 * Every prerendered document is the built shell with a head swap. That is fine
 * for a reader who runs JS, but a crawler or a no-JS client gets a correct
 * `<title>` over an empty body — indistinguishable from a page that failed to
 * load. The fallback sits beside the mount container, outside React's control.
 *
 * The copy deliberately states what the page is *for* without claiming a result
 * exists: it says the tool needs a query, not that data is missing.
 */
const SHELL_MOUNT_PATTERN = /<div\b[^>]*\bid=["'](?:root|app)["'][^>]*>\s*<\/div>/i;

const SHELL_FALLBACK_STYLE =
  "<style>html,body{margin:0;padding:0}" +
  ".soymutdb-shell-fallback{position:absolute;top:0;left:0;right:0;padding:16px}" +
  "body:has(#root > *) .soymutdb-shell-fallback{display:none}</style>";

function shellFallback(entry: StaticRouteEntry): string {
  const summary = entry.description ? `<p>${escapeHtml(entry.description)}</p>` : "";
  return (
    `<div class="soymutdb-shell-fallback">` +
    `<h1>${escapeHtml(entry.title)}</h1>` +
    summary +
    `<noscript>This page is a web application: enable JavaScript to load it.</noscript>` +
    `</div>`
  );
}

/**
 * Replace `<title>` and append page metadata before `</head>`.
 *
 * `shellFallback: true` adds the readable body text a JS-only page needs. It is
 * opt-in because the build script that writes content-bearing documents calls
 * this same function: a document that already carries a real `<main>` must not
 * also carry "enable JavaScript", which would be a lie on a no-JS client.
 */
export function injectPageHead(
  html: string,
  entry: StaticRouteEntry,
  origin?: string,
  siteVariant: SiteVariant = "external",
  options: { shellFallback?: boolean } = { shellFallback: true },
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
  // The fallback goes *after* the mount container, never inside it: the
  // content-snapshot build only recognises an empty `#root`, and `createRoot`
  // clears that node on boot anyway. Sibling text survives for the crawler that
  // never runs the app; text inside the mount would be dropped on boot.
  const mountable = options.shellFallback && SHELL_MOUNT_PATTERN.test(document);
  const withFallback = mountable
    ? document.replace(SHELL_MOUNT_PATTERN, (match) => `${match}${shellFallback(entry)}`)
    : document;
  if (mountable) tags.push(SHELL_FALLBACK_STYLE);
  if (tags.length === 0) return withFallback;
  return withFallback.replace("</head>", `  ${tags.join("\n    ")}\n  </head>`);
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
