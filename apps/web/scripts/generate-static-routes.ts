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
 * ## Released entity documents
 *
 * `SOYMUTDB_ENTITY_SNAPSHOT` names a JSON file listing the entities this
 * deployment may prerender (schema in `src/lib/entity-snapshot.ts`). Each entry
 * becomes `<dist>/genes/<public_id>/index.html` with a real `<main>` body —
 * title, coordinates, strand, assembly and release — so the record page is a
 * document rather than the "enable JavaScript" shell.
 *
 * Without the variable, or with an empty `entities` array, no entity document is
 * written. That default is the contract: a record page is prerendered because
 * the release snapshot says the record exists, never because a route is marked
 * eligible.
 *
 * Origins come from SOYMUTDB_SITE_URL; without one the documents still get
 * their titles but no canonical/sitemap URLs are invented.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { normalizeBasePath } from "@soymutdb/shared/deployment";

import { PORTAL_ROUTES } from "../src/router/routes";
import {
  assertEntitySnapshotRelease,
  normalizeEntitySnapshot,
  planEntityDocuments,
  type EntityDocument,
} from "../src/lib/entity-snapshot";
import { injectStaticContent } from "../src/lib/static-content-render";
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

/** `SOYMUTDB_RELEASE_ID` (same contract as `content-snapshot-build.ts`). */
function resolveExpectedReleaseId(value: string | undefined): number | undefined {
  const trimmed = value?.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(`SOYMUTDB_RELEASE_ID must be a positive integer: ${JSON.stringify(trimmed)}`);
  }
  return parsed;
}

/**
 * Read the entity snapshot named by the build, if any.
 *
 * Returns `[]` when the variable is unset or empty (the fail-closed default) and
 * throws on anything unreadable or invalid: a snapshot that cannot be trusted
 * must stop the build instead of silently publishing a subset of the records.
 */
function loadEntityDocuments(
  snapshotPath: string | undefined,
  env: NodeJS.ProcessEnv,
): EntityDocument[] {
  const configured = snapshotPath?.trim();
  if (!configured) {
    console.log(
      "[static-routes] SOYMUTDB_ENTITY_SNAPSHOT is not set — no entity document is " +
        "prerendered; every record route keeps the SPA shell",
    );
    return [];
  }
  const file = resolve(process.cwd(), configured);
  if (!existsSync(file)) {
    // The base is the package directory, which is not obvious from the shell
    // that sets the variable: `apps/web/fixtures/x.json` resolves to
    // `apps/web/apps/web/fixtures/x.json` and fails here. Say the base out loud
    // rather than leaving the reader to infer it from the doubled path.
    throw new Error(
      `SOYMUTDB_ENTITY_SNAPSHOT points at ${file}, which does not exist: ` +
        `paths resolve against ${process.cwd()} (the package directory), ` +
        "so a repository-relative path needs its `apps/web/` prefix removed. " +
        "An absent snapshot must be an absent variable, not a missing file",
    );
  }
  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(file, "utf8")) as unknown;
  } catch (error) {
    throw new Error(`${file} is not valid JSON: ${(error as Error).message}`, { cause: error });
  }
  const snapshot = normalizeEntitySnapshot(raw);
  assertEntitySnapshotRelease(snapshot, resolveExpectedReleaseId(env.SOYMUTDB_RELEASE_ID));
  const documents = planEntityDocuments(snapshot, {
    basePath: normalizeBasePath(env.VITE_BASE_URL),
  });
  console.log(
    `[static-routes] ${file} supplies ${documents.length} entity document(s) ` +
      `(release ${snapshot.entities[0]?.release_id ?? "—"})`,
  );
  return documents;
}

const DIST_DIR = resolve(
  process.cwd(),
  process.env.SOYMUTDB_DIST_DIR?.trim() || "dist",
);
const siteVariant = resolveSiteVariant(process.env.VITE_SITE_VARIANT);
const origin = process.env.SOYMUTDB_SITE_URL?.trim() || undefined;

const indexHtml = readFileSync(join(DIST_DIR, "index.html"), "utf8");

// The internal variant never publishes a record document, so it never reads the
// snapshot file — same boundary as the content snapshot.
const entityDocuments =
  siteVariant === "external"
    ? loadEntityDocuments(process.env.SOYMUTDB_ENTITY_SNAPSHOT, process.env)
    : [];

const entries = deriveStaticRouteEntries(PORTAL_ROUTES, siteVariant, {
  entityDocuments: entityDocuments.map((document) => ({
    path: document.path,
    templatePath: document.templatePath,
    title: document.title,
    description: document.description,
  })),
});
const entityPaths = new Set(entityDocuments.map((document) => document.path));

for (const entry of entries) {
  // Entity documents are written below, with a real body instead of the shell
  // fallback; writing the shell here first would only be overwritten.
  if (entityPaths.has(entry.path)) continue;
  const target = join(DIST_DIR, directoryIndexPath(entry.path));
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, injectPageHead(indexHtml, entry, origin, siteVariant));
  console.log(`[static-routes] ${entry.path} -> ${target.slice(DIST_DIR.length + 1)}`);
}

for (const document of entityDocuments) {
  const target = join(DIST_DIR, document.relativePath);
  const entry = entries.find((candidate) => candidate.path === document.path);
  if (!entry) {
    throw new Error(
      `[static-routes] ${document.path} did not survive route derivation; ` +
        `its template ${document.templatePath} is not a prerenderable route`,
    );
  }
  mkdirSync(dirname(target), { recursive: true });
  const shell = injectPageHead(indexHtml, entry, origin, siteVariant, {
    // The document gets a real <main> below; "enable JavaScript" would then be
    // false for exactly the client it is written for.
    shellFallback: false,
  });
  // No client payload: the SPA refetches the record from the API when it boots,
  // and a bootstrap blob would be a second, stale source for the same rows.
  writeFileSync(target, injectStaticContent(shell, document.mainHtml, ""));
  console.log(
    `[static-routes] ${document.path} -> ${target.slice(DIST_DIR.length + 1)} (entity)`,
  );
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
  `[static-routes] enumerated ${entries.length} document(s) for the ${siteVariant} variant ` +
    `(${entityDocuments.length} entity)`,
);