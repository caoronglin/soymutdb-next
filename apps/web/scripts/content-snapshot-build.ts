#!/usr/bin/env tsx
/**
 * Render the public content documents of the external artifact.
 *
 * Input : <dist>/data/content.json, written by `fetch-content-snapshot.ts`.
 * Output: the built documents of the three stable public content routes plus
 *         one document per statically generatable news article:
 *
 *           <dist>/about/index.html
 *           <dist>/publications/index.html
 *           <dist>/news/index.html
 *           <dist>/news/<slug>/index.html
 *
 * Each document is the built Umi shell (the same bytes
 * `generate-static-routes.ts` copies) with the page title/description
 * injected and a real `<main>` body plus the `#rl-bootstrap` JSON payload
 * placed inside `#root`, with the JSON payload outside the mount container.
 *
 * NOT hydration. The body is a pre-rendered public document for crawlers and
 * no-JS clients; the portal boots with `createRoot`, which clears `#root` and
 * renders the React tree, so a JS-capable client sees the app *replace* the
 * static body. Real hydration requires the same component tree on both sides
 * and belongs to the app entry + routes, not to this build step.
 *
 * Ownership rules:
 *   - external variant only. The internal variant returns before the snapshot
 *     file is opened.
 *   - a missing snapshot is a logged skip, not a failure: the artifacts stay
 *     exactly as `generate-static-routes.ts` left them.
 *   - the snapshot file is re-validated here (schema, external, release) even
 *     though the fetch step validated it: the artifact is built from a file on
 *     disk and must not assume it is trustworthy.
 *   - visibility-window articles (`news_detail[slug] === null`) never get a
 *     document, and a document left over from an earlier build for such an
 *     article is removed so a withdrawn article stops being published.
 *   - richtext is sanitised here with DOMPurify + jsdom (the server's bleach
 *     pass is the first line of defence, this is the second), never with a
 *     regular expression.
 *
 * Runs after `generate-static-routes.ts` and before `finalize-csp.ts` (see
 * `scripts/build-sites.ts`): this step writes HTML, and the CSP hashes must
 * be computed from the final bytes.
 *
 * Usage: tsx scripts/content-snapshot-build.ts
 * Env:   SOYMUTDB_DIST_DIR, VITE_SITE_VARIANT, SOYMUTDB_RELEASE_ID,
 *        SOYMUTDB_SITE_URL
 */

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import createDOMPurify from "dompurify";
import { normalizeBasePath } from "@soymutdb/shared/deployment";
// jsdom ships no bundled types.
// @ts-expect-error jsdom has no bundled types
import jsdomPkg from "jsdom";

import { deriveStaticRouteEntries, injectPageHead, renderSitemap, type SiteVariant } from "../src/lib/static-routes";
import { PORTAL_ROUTES } from "../src/router/routes";
import {
  assertSnapshotRelease,
  bootstrapScriptTag,
  contentDocumentRelativePath,
  injectStaticContent,
  normalizeContentSnapshot,
  planContentPages,
  resolveExpectedReleaseId,
  type PublicContentSnapshot,
  type RenderDependencies,
} from "../src/lib/static-content-render";
import {
  SNAPSHOT_RELATIVE_PATH,
  isProductionBuild,
  resolveSiteVariant,
} from "./fetch-content-snapshot";

const { JSDOM } = jsdomPkg as {
  JSDOM: new (html?: string) => { window: Window & typeof globalThis };
};

const CONTENT_DOCUMENT_MANIFEST = "data/content-documents.json";

function previousDocuments(distDir: string): string[] {
  const path = join(distDir, CONTENT_DOCUMENT_MANIFEST);
  if (!existsSync(path)) return [];
  const value: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string" || !(
    ["about/index.html", "news/index.html", "publications/index.html"].includes(entry) ||
    /^news\/[a-z0-9]+(?:-[a-z0-9]+)*\/index\.html$/.test(entry)
  ))) {
    throw new Error("[content-snapshot] invalid generated-document manifest");
  }
  return value;
}

/**
 * Build-side sanitiser. Same posture as the portal's
 * `src/components/soymutdb-widget.tsx`: DOMPurify's curated HTML profile,
 * interactive tags refused outright, `target` allowed because admin-authored
 * content links out with `target="_blank"`, and a DOM-level hardening pass
 * that adds `rel="noopener noreferrer"` to those links.
 */
const SANITIZE_CONFIG = {
  USE_PROFILES: { html: true },
  ADD_ATTR: ["target"],
  FORBID_TAGS: [
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "textarea",
    "select",
  ],
  FORBID_ATTR: [
    "onerror",
    "onload",
    "onclick",
    "onfocus",
    "onblur",
    "onmouseover",
    "onanimationstart",
  ],
} as const;

export interface BuildRuntime {
  sanitizeHtml: (html: string) => string;
  htmlToText: (html: string) => string;
}

/** Create the jsdom-backed DOM helpers the renderer requires. */
export function createBuildRuntime(): BuildRuntime {
  const { window } = new JSDOM("");
  // DOMPurify types its window as a structural subset; the jsdom window
  // satisfies it at runtime.
  const DOMPurify = createDOMPurify(
    window as unknown as Parameters<typeof createDOMPurify>[0],
  );
  const document = window.document;

  const sanitizeHtml = (html: string): string => {
    const sanitized = String(DOMPurify.sanitize(html, SANITIZE_CONFIG as never));
    // Hardening through the DOM, never by string concatenation: it can only
    // add an attribute, never bring back anything the sanitizer removed.
    const template = document.createElement("template");
    template.innerHTML = sanitized;
    template.content.querySelectorAll('a[target="_blank"]').forEach((link) => {
      link.setAttribute("rel", "noopener noreferrer");
    });
    return template.innerHTML;
  };

  const parser = new window.DOMParser();
  const htmlToText = (html: string): string => {
    const parsed = parser.parseFromString(html, "text/html");
    return (parsed.body?.textContent ?? "").replace(/\s+/g, " ").trim();
  };

  return { sanitizeHtml, htmlToText };
}

function loadSnapshot(distDir: string, env: NodeJS.ProcessEnv): PublicContentSnapshot | null {
  const snapshotFile = join(distDir, SNAPSHOT_RELATIVE_PATH);
  if (!existsSync(snapshotFile)) return null;
  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(snapshotFile, "utf8")) as unknown;
  } catch (error) {
    throw new Error(
      `[content-snapshot] ${SNAPSHOT_RELATIVE_PATH} is not valid JSON: ${(error as Error).message}`,
      { cause: error },
    );
  }
  const snapshot = normalizeContentSnapshot(raw);
  assertSnapshotRelease(snapshot, resolveExpectedReleaseId(env.SOYMUTDB_RELEASE_ID));
  return snapshot;
}

export interface BuildOptions {
  env: NodeJS.ProcessEnv;
  runtime: BuildRuntime;
  /** Overridable for tests; defaults to a fresh jsdom runtime. */
  distDir?: string;
}

export interface BuildReport {
  status: "written" | "skipped";
  reason?: string;
  documents: string[];
  removed: string[];
}

/**
 * Write the content documents for the external variant.
 *
 * Throws on any inconsistency (bad snapshot, missing shell, route collision):
 * a partially-rendered content site is worse than a build that stops.
 */
export function buildContentDocuments(options: BuildOptions): BuildReport {
  const { env, runtime } = options;
  const distDir = options.distDir ?? resolve(process.cwd(), env.SOYMUTDB_DIST_DIR?.trim() || "dist");

  const variant: SiteVariant = resolveSiteVariant(env);
  if (variant !== "external") {
    // Before any read: the internal artifact must never consume the external
    // snapshot, not even to decide it has nothing to do.
    return { status: "skipped", reason: "internal-variant", documents: [], removed: [] };
  }

  const snapshot = loadSnapshot(distDir, env);
  if (!snapshot) {
    return { status: "skipped", reason: "no-snapshot", documents: [], removed: [] };
  }

  const shellFile = join(distDir, "index.html");
  if (!existsSync(shellFile)) {
    throw new Error(
      `[content-snapshot] ${shellFile} is missing — run the Umi build (or ` +
        "generate-static-routes.ts) before rendering content documents",
    );
  }
  const shell = readFileSync(shellFile, "utf8");
  const origin = env.SOYMUTDB_SITE_URL?.trim() || undefined;
  const basePath = normalizeBasePath(env.VITE_BASE_URL);

  const dependencies: RenderDependencies = {
    basePath,
    sanitizeHtml: runtime.sanitizeHtml,
    htmlToText: runtime.htmlToText,
  };
  const pages = planContentPages(snapshot, dependencies);
  // Validate ownership metadata before writing any new document.
  const previous = previousDocuments(distDir);

  const documents: string[] = [];
  for (const page of pages) {
    const relative = contentDocumentRelativePath(page.routePath);
    const target = join(distDir, relative);
    const existed = existsSync(target);
    const document = injectPageHead(
      shell,
      {
        path: `${basePath}${page.routePath.slice(1)}`,
        title: page.title,
        description: page.description,
        includeInSitemap: false,
      },
      origin,
      "external",
    );
    const html = injectStaticContent(
      document,
      page.mainHtml,
      bootstrapScriptTag(page.bootstrap),
    );
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, html, "utf8");
    documents.push(relative);
    console.log(
      `[content-snapshot] ${relative} (${page.kind})` +
        (existed ? " — replaces the route shell" : ""),
    );
  }

  // A visibility-window article (detail === null) must not stay published from
  // an earlier build, and neither must a slug that left the snapshot entirely.
  const removed: string[] = [];
  const generated = new Set(documents);
  for (const relative of previous) {
    if (generated.has(relative)) continue;
    const target = join(distDir, relative);
    if (!existsSync(target) && !existsSync(`${target}.gz`)) continue;
    rmSync(target, { force: true });
    rmSync(`${target}.gz`, { force: true });
    removed.push(relative);
  }
  const newsDir = join(distDir, "news");
  if (existsSync(newsDir)) {
    const detail = snapshot.news_detail;
    const listSlugs = new Set(snapshot.news.items.map((item) => item.slug));
    const candidates = [Object.keys(detail), [...listSlugs]].flat();
    for (const slug of new Set(candidates)) {
      if (detail[slug] !== undefined && detail[slug] !== null) continue;
      const relative = contentDocumentRelativePath(`/news/${slug}`);
      const target = join(distDir, relative);
      if (!existsSync(target) && !existsSync(`${target}.gz`)) continue;
      rmSync(target, { force: true });
      rmSync(`${target}.gz`, { force: true });
      removed.push(relative);
      console.log(`[content-snapshot] removed ${relative} (not statically generatable)`);
    }
  }

  const manifest = join(distDir, CONTENT_DOCUMENT_MANIFEST);
  mkdirSync(dirname(manifest), { recursive: true });
  writeFileSync(manifest, JSON.stringify(documents), "utf8");
  if (origin) {
    const entries = deriveStaticRouteEntries(PORTAL_ROUTES, "external");
    const known = new Set(entries.map((entry) => entry.path));
    for (const page of pages) {
      if (known.has(page.routePath)) continue;
      entries.push({ path: page.routePath, title: page.title, includeInSitemap: true });
    }
    writeFileSync(join(distDir, "sitemap.xml"), renderSitemap(
      entries.map((entry) => ({ ...entry, path: `${basePath}${entry.path.slice(1)}` })),
      origin,
    ), "utf8");
  }

  return { status: "written", documents, removed };
}

function main(): void {
  const env = process.env;
  const report = buildContentDocuments({ env, runtime: createBuildRuntime() });
  if (report.status === "skipped") {
    console.log(
      `[content-snapshot] content documents skipped (${report.reason ?? "unknown"}) — ` +
        "the build keeps the documents generate-static-routes.ts produced",
    );
    return;
  }
  console.log(
    `[content-snapshot] wrote ${report.documents.length} content document(s)` +
      (report.removed.length ? `, removed ${report.removed.length} withdrawn article(s)` : "") +
      `${isProductionBuild(env) ? " (production build)" : ""}`,
  );
}

const invokedDirectly =
  process.argv[1] !== undefined &&
  resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));

if (invokedDirectly) {
  try {
    main();
  } catch (error) {
    console.error((error as Error)?.message ?? String(error));
    process.exit(1);
  }
}
