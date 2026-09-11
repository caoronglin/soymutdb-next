/**
 * Regression tests for the Pages smoke test (scripts/smoke-pages.ts).
 *
 * Goal: abnormal releases must keep being blocked by the deploy gate —
 * in particular malformed content snapshots and sitemaps without news URLs.
 *
 * runChecks() is I/O-isolated (distDir passed in), so each case builds a
 * throwaway dist tree in the OS temp dir.
 */

import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { runChecks, type CheckResult } from "../smoke-pages";

const URL = "https://api.example.com/api/v1/content/snapshot";

function makeDist(): string {
  const dir = mkdtempSync(join(tmpdir(), "smoke-pages-test-"));
  mkdirSync(join(dir, "data"), { recursive: true });
  mkdirSync(join(dir, "news"), { recursive: true });
  return dir;
}

function validSnapshot(): string {
  return JSON.stringify({
    schema_version: 2,
    generated_at: "2026-08-09T12:00:00.000Z",
    news: { source_total: 1, included_total: 1, truncated: false, items: [] },
    news_detail: { "test-news": { slug: "test-news", title_en: "T" } },
    about: null,
  });
}

/** Minimal SSG page mirroring the real base-template output shape. */
function validNewsPage(): string {
  return [
    "<!doctype html><html><head>",
    '<script type="application/ld+json">{"@type":"Article"}</script>',
    "</head><body>",
    '<div id="root"><article><h1>Test News</h1></article></div>',
    '<script type="application/json" id="rl-bootstrap">{"page":"news-detail"}</script>',
    "</body></html>",
  ].join("\n");
}

function result(results: CheckResult[], name: string): CheckResult {
  const r = results.find((x) => x.name === name);
  if (!r) throw new Error(`missing check: ${name}`);
  return r;
}

let dist: string;

beforeEach(() => {
  dist = makeDist();
});

afterEach(() => {
  rmSync(dist, { recursive: true, force: true });
});

describe("smoke-pages regression: content snapshot", () => {
  it("blocks an unparseable (malformed JSON) snapshot", () => {
    writeFileSync(join(dist, "data", "content.json"), "{not valid json");
    const results = runChecks({ distDir: dist, snapshotUrl: URL });

    const check = result(results, "dist/data/content.json");
    expect(check.ok).toBe(false);
    expect(check.detail).toMatch(/unparseable/);
    // Downstream checks must not pretend to pass without a valid snapshot.
    expect(result(results, "dist/news/{slug}.html (at least one)").ok).toBe(false);
  });

  it("blocks a snapshot with a wrong schema_version", () => {
    const snap = JSON.parse(validSnapshot()) as Record<string, unknown>;
    snap.schema_version = 1;
    writeFileSync(join(dist, "data", "content.json"), JSON.stringify(snap));
    const results = runChecks({ distDir: dist, snapshotUrl: URL });

    const check = result(results, "dist/data/content.json");
    expect(check.ok).toBe(false);
    expect(check.detail).toContain("invalid schema (version=1)");
  });

  it("blocks a snapshot missing generated_at", () => {
    const snap = JSON.parse(validSnapshot()) as Record<string, unknown>;
    delete snap.generated_at;
    writeFileSync(join(dist, "data", "content.json"), JSON.stringify(snap));
    const results = runChecks({ distDir: dist, snapshotUrl: URL });

    expect(result(results, "dist/data/content.json").ok).toBe(false);
  });

  it("blocks a snapshot with no news_detail entries and no generated pages", () => {
    const snap = JSON.parse(validSnapshot()) as Record<string, unknown>;
    snap.news_detail = {};
    writeFileSync(join(dist, "data", "content.json"), JSON.stringify(snap));
    const results = runChecks({ distDir: dist, snapshotUrl: URL });

    const check = result(results, "dist/news/{slug}.html (at least one)");
    expect(check.ok).toBe(false);
    expect(check.detail).toMatch(/no detail pages generated/);
  });

  it("blocks a detail page missing rl-bootstrap or JSON-LD", () => {
    writeFileSync(join(dist, "data", "content.json"), validSnapshot());
    writeFileSync(
      join(dist, "news", "test-news.html"),
      "<html><body><div id=\"root\"><p>x</p></div></body></html>",
    );
    const results = runChecks({ distDir: dist, snapshotUrl: URL });

    const check = result(results, "dist/news/test-news.html");
    expect(check.ok).toBe(false);
    expect(check.detail).toMatch(/rl-bootstrap=false|json-ld=false/);
    expect(result(results, "dist/news/{slug}.html (at least one)").ok).toBe(false);
  });

  it("blocks a detail page with executable markup in the body region", () => {
    writeFileSync(join(dist, "data", "content.json"), validSnapshot());
    writeFileSync(
      join(dist, "news", "test-news.html"),
      [
        "<html><body>",
        '<div id="root"><p>ok</p><img src="x" onerror="alert(1)"></div>',
        '<script type="application/json" id="rl-bootstrap">{}</script>',
        "</body></html>",
      ].join("\n"),
    );
    const results = runChecks({ distDir: dist, snapshotUrl: URL });

    expect(result(results, "dist/news/test-news.html").ok).toBe(false);
    expect(result(results, "dist/news/{slug}.html (at least one)").ok).toBe(false);
  });
});

describe("smoke-pages regression: sitemap news URLs", () => {
  it("blocks a missing sitemap", () => {
    writeFileSync(join(dist, "data", "content.json"), validSnapshot());
    writeFileSync(join(dist, "news", "index.html"), validNewsPage());
    writeFileSync(join(dist, "news", "test-news.html"), validNewsPage());
    writeFileSync(join(dist, "about.html"), validNewsPage());
    const results = runChecks({ distDir: dist, snapshotUrl: URL });

    expect(result(results, "sitemap.xml with news URLs").ok).toBe(false);
  });

  it("blocks a sitemap without news URLs (ssg-content did not run)", () => {
    writeFileSync(join(dist, "data", "content.json"), validSnapshot());
    writeFileSync(join(dist, "news", "index.html"), validNewsPage());
    writeFileSync(join(dist, "news", "test-news.html"), validNewsPage());
    writeFileSync(join(dist, "about.html"), validNewsPage());
    writeFileSync(
      join(dist, "sitemap.xml"),
      '<?xml version="1.0"?><urlset><url><loc>https://x/index.html</loc></url></urlset>',
    );
    const results = runChecks({ distDir: dist, snapshotUrl: URL });

    const check = result(results, "sitemap.xml with news URLs");
    expect(check.ok).toBe(false);
    expect(check.detail).toMatch(/no news URLs appended/);
  });
});

describe("smoke-pages regression: happy path stays green", () => {
  it("passes a fully valid dist tree", () => {
    writeFileSync(join(dist, "data", "content.json"), validSnapshot());
    writeFileSync(join(dist, "news", "index.html"), validNewsPage());
    writeFileSync(join(dist, "news", "test-news.html"), validNewsPage());
    writeFileSync(join(dist, "about.html"), validNewsPage());
    writeFileSync(
      join(dist, "sitemap.xml"),
      '<?xml version="1.0"?><urlset><url><loc>https://x/news</loc></url></urlset>',
    );
    const results = runChecks({ distDir: dist, snapshotUrl: URL });

    expect(results.every((r) => r.ok)).toBe(true);
    expect(results).toHaveLength(6);
  });

  it("reports the configured URL and still gates when unset", () => {
    writeFileSync(join(dist, "data", "content.json"), validSnapshot());
    const results = runChecks({ distDir: dist, snapshotUrl: "" });

    expect(result(results, "CONTENT_SNAPSHOT_URL configured").ok).toBe(false);
    expect(result(results, "CONTENT_SNAPSHOT_URL configured").detail).toMatch(
      /secret CONTENT_SNAPSHOT_URL/,
    );
  });
});
