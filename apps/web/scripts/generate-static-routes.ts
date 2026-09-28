#!/usr/bin/env tsx
/**
 * Static route enumeration for the React portal.
 *
 * Runs after the Umi build. For every route whose metadata marks it prerenderable
 * it writes `<dist>/<path>/index.html` (the built shell with the page title,
 * description, and canonical link injected) so static hosts serve a real
 * document per route instead of relying on an SPA fallback. It also writes:
 *
 *   routes.json   the enumeration itself (site variant + entries)
 *   robots.txt    external: allow + sitemap; internal: disallow everything
 *   sitemap.xml   external only, and only when a site origin is known
 *
 * Origins come from SOYMUTDB_SITE_URL; without one the documents still get
 * their titles but no canonical/sitemap URLs are invented.
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { PORTAL_ROUTES } from "../src/router/routes";
import {
  deriveStaticRouteEntries,
  directoryIndexPath,
  injectPageHead,
  renderRobots,
  renderSitemap,
  type SiteVariant,
} from "../src/lib/static-routes";

function resolveSiteVariant(value: unknown): SiteVariant {
  const normalized = String(value ?? "external").trim().toLowerCase();
  if (normalized === "external" || normalized === "internal") return normalized;
  throw new Error(
    `VITE_SITE_VARIANT must be exactly "external" or "internal"; got ${JSON.stringify(value)}`,
  );
}

const DIST_DIR = resolve(
  process.cwd(),
  process.env.SOYMUTDB_DIST_DIR?.trim() || "dist",
);
const siteVariant = resolveSiteVariant(process.env.VITE_SITE_VARIANT);
const origin = process.env.SOYMUTDB_SITE_URL?.trim() || undefined;

const indexHtml = readFileSync(join(DIST_DIR, "index.html"), "utf8");
const entries = deriveStaticRouteEntries(PORTAL_ROUTES, siteVariant);

for (const entry of entries) {
  const target = join(DIST_DIR, directoryIndexPath(entry.path));
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, injectPageHead(indexHtml, entry, origin, siteVariant));
  console.log(`[static-routes] ${entry.path} -> ${target.slice(DIST_DIR.length + 1)}`);
}

writeFileSync(
  join(DIST_DIR, "routes.json"),
  `${JSON.stringify({ siteVariant, origin: origin ?? null, entries }, null, 2)}\n`,
);
writeFileSync(join(DIST_DIR, "robots.txt"), renderRobots(siteVariant, origin));

if (siteVariant === "external" && origin) {
  writeFileSync(join(DIST_DIR, "sitemap.xml"), renderSitemap(entries, origin));
  console.log("[static-routes] sitemap.xml written");
}

console.log(
  `[static-routes] enumerated ${entries.length} document(s) for the ${siteVariant} variant`,
);
