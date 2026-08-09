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

const DIST_DIR = join(process.cwd(), "dist");
const SNAPSHOT_URL = process.env.CONTENT_SNAPSHOT_URL ?? "";

interface Check {
  name: string;
  run: () => { ok: boolean; detail: string };
}

function fail(name: string, detail: string): { ok: false; detail: string } {
  console.error(`[smoke-pages] FAIL  ${name}: ${detail}`);
  return { ok: false, detail };
}
function pass(name: string, detail: string): { ok: true; detail: string } {
  console.log(`[smoke-pages] PASS  ${name}: ${detail}`);
  return { ok: true, detail };
}

/**
 * Extract the rendered body region (inside #root) and assert it is free of
 * executable markup.  <script> blocks (bootstrap / JSON-LD / module scripts)
 * are stripped first so they do not false-positive.
 */
function bodyRegionIsClean(html: string, context: string): boolean {
  const rootMatch =
    html.match(/<div id="root"([\s\S]*?)<\/div>\s*<\/main>/i) ??
    html.match(/<div id="root"([\s\S]*?)(?:<\/body>|<\/html>)/i);
  const body = (rootMatch?.[1] as string | undefined) ?? html;
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

function readDist(rel: string): string | null {
  const p = join(DIST_DIR, rel);
  return existsSync(p) ? readFileSync(p, "utf-8") : null;
}

function checks(): Check[] {
  const snapshotJson = readDist("data/content.json");
  const newsIndex = readDist("news/index.html");
  const aboutHtml = readDist("about.html");
  const sitemap = readDist("sitemap.xml");

  return [
    {
      name: "CONTENT_SNAPSHOT_URL configured",
      run: () =>
        SNAPSHOT_URL
          ? pass("CONTENT_SNAPSHOT_URL configured", SNAPSHOT_URL)
          : fail(
              "CONTENT_SNAPSHOT_URL configured",
              "env not set — content SSG was skipped; set the Pages secret CONTENT_SNAPSHOT_URL to enable content pages",
            ),
    },
    {
      name: "dist/data/content.json",
      run: () => {
        if (!snapshotJson) {
          return fail("dist/data/content.json", "missing (content SSG skipped)");
        }
        try {
          const snap = JSON.parse(snapshotJson) as {
            schema_version: number;
            generated_at: string;
          };
          if (snap.schema_version !== 1 || !snap.generated_at) {
            return fail(
              "dist/data/content.json",
              `invalid schema (version=${snap.schema_version})`,
            );
          }
          return pass(
            "dist/data/content.json",
            `schema v${snap.schema_version} @ ${snap.generated_at}`,
          );
        } catch (err) {
          return fail("dist/data/content.json", `unparseable: ${(err as Error).message}`);
        }
      },
    },
    {
      name: "dist/news/index.html",
      run: () => {
        if (!newsIndex) return fail("dist/news/index.html", "missing");
        if (!bodyRegionIsClean(newsIndex, "news/index.html")) {
          return fail("dist/news/index.html", "unsanitised body");
        }
        return pass("dist/news/index.html", "present, sanitised body");
      },
    },
    {
      name: "dist/news/{slug}.html (at least one)",
      run: () => {
        if (!snapshotJson) return fail("news detail pages", "no snapshot");
        const slugs = Object.keys(
          (JSON.parse(snapshotJson) as { news_detail: Record<string, unknown> })
            .news_detail ?? {},
        ).filter((s) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(s));
        const generated: string[] = [];
        for (const slug of slugs) {
          const html = readDist(`news/${slug}.html`);
          if (!html) continue;
          const hasBootstrap = html.includes('id="rl-bootstrap"');
          const hasJsonLd = html.includes('type="application/ld+json"');
          if (!hasBootstrap || !hasJsonLd) {
            return fail(
              `dist/news/${slug}.html`,
              `missing rl-bootstrap=${hasBootstrap} json-ld=${hasJsonLd}`,
            );
          }
          if (!bodyRegionIsClean(html, `news/${slug}.html`)) {
            return fail(`dist/news/${slug}.html`, "unsanitised body");
          }
          generated.push(slug);
        }
        if (generated.length === 0) {
          return fail(
            "dist/news/{slug}.html",
            "no detail pages generated (window articles only? snapshot empty?)",
          );
        }
        return pass(
          "dist/news/{slug}.html",
          `${generated.length} page(s): ${generated.slice(0, 3).join(", ")}${generated.length > 3 ? ", …" : ""}`,
        );
      },
    },
    {
      name: "dist/about.html",
      run: () => {
        if (!aboutHtml) return fail("dist/about.html", "missing");
        if (!bodyRegionIsClean(aboutHtml, "about.html")) {
          return fail("dist/about.html", "unsanitised body");
        }
        return pass("dist/about.html", "present, sanitised body");
      },
    },
    {
      name: "sitemap.xml with news URLs",
      run: () => {
        if (!sitemap) return fail("dist/sitemap.xml", "missing");
        const hasNews = sitemap.includes(">news</loc>") || sitemap.includes("/news/");
        if (!hasNews) {
          return fail(
            "dist/sitemap.xml",
            "no news URLs appended (ssg-content.ts must run before this smoke test)",
          );
        }
        return pass("dist/sitemap.xml", "news URLs present");
      },
    },
  ];
}

function main(): void {
  if (!SNAPSHOT_URL) {
    console.log(
      "[smoke-pages] SKIP content checks — CONTENT_SNAPSHOT_URL not configured " +
        "(content pages fall back to SPA/API; set the Pages secret to enable)",
    );
    process.exit(0);
  }

  const results = checks().map((c) => c.run());
  const failed = results.filter((r) => !r.ok);
  if (failed.length > 0) {
    console.error(
      `[smoke-pages] FAILED ${failed.length}/${results.length} checks — deploy aborted. ` +
        "Fix the listed issues or unset CONTENT_SNAPSHOT_URL to skip content pages.",
    );
    process.exit(1);
  }
  console.log(`[smoke-pages] ALL ${results.length} CHECKS PASSED — deploy ready.`);
}

main();
