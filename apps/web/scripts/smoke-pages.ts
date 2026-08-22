#!/usr/bin/env tsx
/**
 * Pages deployment smoke test (E2 post-deploy gate).
 *
 * Verifies, BEFORE the deploy step ships dist to gh-pages:
 *
 *   1. CONTENT_SNAPSHOT_URL is configured (opt-in feature gate).
 *      - Not set  -> clear log line, skip content checks, EXIT 0
 *                    (existing deploy pipeline stays green).
 *      - Set      -> content pages MUST be present and clean.
 *   2. dist/data/content.json exists and parses (schema_version/generated_at).
 *   3. dist/news/index.html exists, contains sanitised static content
 *      (no script tags, on* handlers or javascript: URIs in the rendered
 *      body region).
 *   4. At least one dist/news/{slug}.html exists with rl-bootstrap and
 *      JSON-LD, and its body region is sanitised.
 *   5. dist/about.html exists and its body region is sanitised.
 *   6. dist/sitemap.xml exists and contains news URLs.
 *
 * Any FAIL prints an explicit log line; failures exit 1 so CI stops before
 * publishing stale or un-sanitised content pages.
 */

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const DIST_DIR = join(process.cwd(), "dist");
const SNAPSHOT_URL = process.env.CONTENT_SNAPSHOT_URL ?? "";

/**
 * Extract the independent static SSG region and assert it is free of
 * executable markup.  <script> blocks (bootstrap / JSON-LD / module scripts)
 * are stripped first so they do not false-positive.
 */
function bodyRegionIsClean(html: string, context: string): boolean {
  const staticMatch = html.match(
    /<!-- ssg-content:start -->([\s\S]*?)<!-- ssg-content:end -->/i,
  );
  const legacyRootMatch =
    html.match(/<div id="root"([\s\S]*?)<\/div>\s*<\/main>/i) ??
    html.match(/<div id="root"([\s\S]*?)(?:<\/body>|<\/html>)/i);
  const body =
    (staticMatch?.[1] as string | undefined) ??
    (legacyRootMatch?.[1] as string | undefined) ??
    html;
  const withoutScripts = body.replace(/<script[\s\S]*?<\/script>/gi, "");
  const dirty = /<(script|style|iframe|object|embed)\b|on\w+\s*=|javascript:/i.test(
    withoutScripts,
  );
  if (dirty) {
    console.error(
      `[smoke-pages]   -> executable markup detected in ${context} body region`,
    );
    return false;
  }
  return true;
}

/* ------------------------------------------------------------------ */
/*  Testable core (unit tests in scripts/__tests__/smoke-pages.test.ts) */
/* ------------------------------------------------------------------ */

export interface CheckResult {
  name: string;
  ok: boolean;
  detail: string;
}

export interface SmokeOptions {
  distDir: string;
  snapshotUrl: string;
}

/** Build the full check list against a given dist dir (I/O-isolated). */
export function runChecks(opts: SmokeOptions): CheckResult[] {
  const distDir = opts.distDir;
  const snapshotUrl = opts.snapshotUrl;

  const readFile = (rel: string): string | null => {
    const p = join(distDir, rel);
    return existsSync(p) ? readFileSync(p, "utf-8") : null;
  };

  const snapshotJson = readFile("data/content.json");
  const newsIndex = readFile("news/index.html");
  const aboutHtml = readFile("about.html");
  const sitemap = readFile("sitemap.xml");

  const results: CheckResult[] = [];

  results.push({
    name: "CONTENT_SNAPSHOT_URL configured",
    ok: Boolean(snapshotUrl),
    detail: snapshotUrl
      ? snapshotUrl
      : "env not set — content SSG was skipped; set the Pages secret CONTENT_SNAPSHOT_URL to enable content pages",
  });

  // dist/data/content.json — must exist, parse, and carry a valid schema.
  let snapshot: { news_detail: Record<string, unknown> } | null = null;
  if (!snapshotJson) {
    results.push({
      name: "dist/data/content.json",
      ok: false,
      detail: "missing (content SSG skipped)",
    });
  } else {
    try {
      const snap = JSON.parse(snapshotJson) as {
        schema_version: number;
        generated_at: string;
        news_detail?: Record<string, unknown>;
      };
      if (snap.schema_version !== 1 || !snap.generated_at) {
        results.push({
          name: "dist/data/content.json",
          ok: false,
          detail: `invalid schema (version=${String(snap.schema_version)})`,
        });
      } else {
        snapshot = { news_detail: snap.news_detail ?? {} };
        results.push({
          name: "dist/data/content.json",
          ok: true,
          detail: `schema v${snap.schema_version} @ ${snap.generated_at}`,
        });
      }
    } catch (err) {
      results.push({
        name: "dist/data/content.json",
        ok: false,
        detail: `unparseable: ${(err as Error).message}`,
      });
    }
  }

  // dist/news/index.html — present with a sanitised body region.
  if (!newsIndex) {
    results.push({ name: "dist/news/index.html", ok: false, detail: "missing" });
  } else if (!bodyRegionIsClean(newsIndex, "news/index.html")) {
    results.push({ name: "dist/news/index.html", ok: false, detail: "unsanitised body" });
  } else {
    results.push({
      name: "dist/news/index.html",
      ok: true,
      detail: "present, sanitised body",
    });
  }

  // dist/news/{slug}.html — at least one detail page with bootstrap + JSON-LD.
  if (!snapshot) {
    results.push({ name: "dist/news/{slug}.html (at least one)", ok: false, detail: "no snapshot" });
  } else {
    const slugs = Object.keys(snapshot.news_detail ?? {}).filter((s) =>
      /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(s),
    );
    const generated: string[] = [];
    let failed = false;
    for (const slug of slugs) {
      const html = readFile(`news/${slug}.html`);
      if (!html) continue;
      const hasBootstrap = html.includes('id="rl-bootstrap"');
      const hasJsonLd = html.includes('type="application/ld+json"');
      if (!hasBootstrap || !hasJsonLd) {
        results.push({
          name: `dist/news/${slug}.html`,
          ok: false,
          detail: `missing rl-bootstrap=${hasBootstrap} json-ld=${hasJsonLd}`,
        });
        failed = true;
        continue;
      }
      if (!bodyRegionIsClean(html, `news/${slug}.html`)) {
        results.push({
          name: `dist/news/${slug}.html`,
          ok: false,
          detail: "unsanitised body",
        });
        failed = true;
        continue;
      }
      generated.push(slug);
    }
    results.push({
      name: "dist/news/{slug}.html (at least one)",
      ok: !failed && generated.length > 0,
      detail:
        generated.length === 0
          ? "no detail pages generated (window articles only? snapshot empty?)"
          : `${generated.length} page(s): ${generated.slice(0, 3).join(", ")}${generated.length > 3 ? ", …" : ""}`,
    });
  }

  // dist/about.html — present with a sanitised body region.
  if (!aboutHtml) {
    results.push({ name: "dist/about.html", ok: false, detail: "missing" });
  } else if (!bodyRegionIsClean(aboutHtml, "about.html")) {
    results.push({ name: "dist/about.html", ok: false, detail: "unsanitised body" });
  } else {
    results.push({ name: "dist/about.html", ok: true, detail: "present, sanitised body" });
  }

  // dist/sitemap.xml — must reference news URLs.  ssg-content.ts appends
  // `<loc>…/news</loc>` (list) and `<loc>…/news/{slug}</loc>` (details).
  if (!sitemap) {
    results.push({ name: "sitemap.xml with news URLs", ok: false, detail: "missing" });
  } else {
    const hasNews = sitemap.includes("/news</loc>") || sitemap.includes("/news/");
    results.push({
      name: "sitemap.xml with news URLs",
      ok: hasNews,
      detail: hasNews
        ? "news URLs present"
        : "no news URLs appended (ssg-content.ts must run before this smoke test)",
    });
  }

  return results;
}

/* ------------------------------------------------------------------ */
/*  CLI entry                                                         */
/* ------------------------------------------------------------------ */

function main(): void {
  if (!SNAPSHOT_URL) {
    console.log(
      "[smoke-pages] SKIP content checks — CONTENT_SNAPSHOT_URL not configured " +
        "(content pages fall back to SPA/API; set the Pages secret to enable)",
    );
    process.exit(0);
  }

  const results = runChecks({ distDir: DIST_DIR, snapshotUrl: SNAPSHOT_URL });
  const failed = results.filter((r) => !r.ok);
  for (const r of results) {
    if (r.ok) {
      console.log(`[smoke-pages] PASS  ${r.name}: ${r.detail}`);
    } else {
      console.error(`[smoke-pages] FAIL  ${r.name}: ${r.detail}`);
    }
  }
  if (failed.length > 0) {
    console.error(
      `[smoke-pages] FAILED ${failed.length}/${results.length} checks — deploy aborted. ` +
        "Fix the listed issues or unset CONTENT_SNAPSHOT_URL to skip content pages.",
    );
    process.exit(1);
  }
  console.log(`[smoke-pages] ALL ${results.length} CHECKS PASSED — deploy ready.`);
}

// CLI entry — only runs when executed directly (tsx scripts/smoke-pages.ts),
// not when imported by unit tests.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
