/**
 * Build-step contract for the public content snapshot.
 *
 * The behaviours pinned here are the ones that would publish something wrong
 * rather than merely fail: a script-injection payload inside the bootstrap
 * JSON, a slug that escapes the news directory, a content snapshot entering
 * the internal artifact, a document built for another release, a visibility
 * window article rendered as a static file, and richtext that reaches a page
 * without going through the build-side sanitiser.
 */

import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readBootstrap } from "./content-snapshot";

import {
  CONTENT_SNAPSHOT_SCHEMA_VERSION,
  assertSnapshotRelease,
  assertSafeSlug,
  bootstrapScriptTag,
  contentDocumentRelativePath,
  injectStaticContent,
  normalizeContentSnapshot,
  planContentPages,
  resolveExpectedReleaseId,
  serializeBootstrap,
  type BootstrapPayload,
  type PublicContentSnapshot,
} from "./static-content-render";
import {
  acquireContentSnapshot,
  isProductionBuild,
  resolveSiteVariant,
} from "../../scripts/fetch-content-snapshot";
import {
  buildContentDocuments,
  createBuildRuntime,
} from "../../scripts/content-snapshot-build";

const GENERATED_AT = "2026-10-13T08:00:00+00:00";

function newsItem(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    slug: "release-2026-10",
    title_en: "Release 2026-10",
    title_zh: "2026-10 版本发布",
    category: "release",
    cover_url: null,
    cover_asset_id: null,
    cover_alt_text: null,
    featured_sort: 0,
    carousel_group: null,
    carousel_sort: 0,
    status: "published",
    is_published: true,
    published_at: "2026-10-01T00:00:00+00:00",
    created_at: "2026-10-01T00:00:00+00:00",
    updated_at: "2026-10-02T00:00:00+00:00",
    ...overrides,
  };
}

function newsDetail(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ...newsItem(overrides),
    content_en: "<p>Body copy for the release.</p>",
    content_zh: null,
    visible_from: null,
    visible_to: null,
    source_platform: null,
    source_url: null,
    source_published_at: null,
    source_synced_at: null,
  };
}

function rawSnapshot(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema_version: CONTENT_SNAPSHOT_SCHEMA_VERSION,
    generated_at: GENERATED_AT,
    site_variant: "external",
    news: {
      source_total: 2,
      included_total: 2,
      truncated: false,
      items: [newsItem(), newsItem({ slug: "withdrawn-article", title_en: "Withdrawn" })],
    },
    news_detail: {
      "release-2026-10": newsDetail(),
      // Visibility window article: included in the list, never generated.
      "withdrawn-article": null,
    },
    about: {
      title_en: "About SoyMutDB",
      title_zh: null,
      summary_en: "A soybean mutant database.",
      summary_zh: null,
      content_en: "<p>About body.</p>",
      content_zh: null,
    },
    publications: [
      {
        title: "A soybean paper",
        title_zh: null,
        authors: "Ronglin T et al.",
        authors_zh: null,
        journal: "Database",
        year: 2026,
        doi: "10.1234/soymutdb.1",
        pmid: null,
        abstract: null,
        abstract_zh: null,
        is_featured: true,
        created_at: "2026-01-01T00:00:00+00:00",
      },
    ],
    static_pages: [],
    ...overrides,
  };
}

function jsonResponse(payload: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json; charset=utf-8" },
    ...init,
  });
}

function makeDist(snapshot: unknown = rawSnapshot()): string {
  const dir = mkdtempSync(join(tmpdir(), "rl-content-snapshot-"));
  writeFileSync(join(dir, "index.html"), SHELL, "utf8");
  mkdirSync(join(dir, "data"), { recursive: true });
  writeFileSync(join(dir, "data", "content.json"), JSON.stringify(snapshot), "utf8");
  return dir;
}

const SHELL = [
  "<!DOCTYPE html>",
  '<html lang="en"><head><title>SoyMutDB</title>',
  '<meta http-equiv="Content-Security-Policy" content="default-src &#x27;self&#x27;" />',
  "</head>",
  '<body><div id="root"></div></body></html>',
].join("");

let distDir: string | undefined;

beforeEach(() => {
  vi.spyOn(console, "log").mockImplementation(() => undefined);
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
  if (distDir) rmSync(distDir, { recursive: true, force: true });
  distDir = undefined;
});

describe("snapshot validation", () => {
  it("rejects an unknown schema_version instead of guessing", () => {
    expect(() => normalizeContentSnapshot(rawSnapshot({ schema_version: 1 }))).toThrow(
      /unsupported schema_version 1/,
    );
    expect(() => normalizeContentSnapshot(rawSnapshot({ schema_version: 3 }))).toThrow(
      /unsupported schema_version 3/,
    );
  });

  it("refuses a snapshot that is not the external variant", () => {
    expect(() => normalizeContentSnapshot(rawSnapshot({ site_variant: "internal" }))).toThrow(
      /site_variant must be "external"/,
    );
    const { site_variant: _omitted, ...withoutVariant } = rawSnapshot();
    expect(() => normalizeContentSnapshot(withoutVariant)).toThrow(/site_variant must be "external"/);
  });

  it("exports only whitelisted public fields", () => {
    const snapshot = normalizeContentSnapshot(
      rawSnapshot({
        secret_internal_field: "do-not-publish",
        news_detail: {
          "release-2026-10": newsDetail({ internal_id: 42 }),
        },
        static_pages: [
          {
            id: 17,
            slug: "guide",
            title_en: "Guide",
            title_zh: null,
            content_en: "<p>Guide body.</p>",
            content_zh: null,
            status: "published",
            summary: null,
            category: null,
            sort_order: 1,
            created_at: GENERATED_AT,
            updated_at: GENERATED_AT,
            author_id: "9f0c",
          },
        ],
      }),
    );

    const serialised = JSON.stringify(snapshot);
    expect(serialised).not.toContain("do-not-publish");
    expect(serialised).not.toContain("internal_id");
    expect(serialised).not.toContain("author_id");
    expect(snapshot.news.items[0]).not.toHaveProperty("id");
    expect(snapshot.news.items[0]).not.toHaveProperty("status");
    expect(snapshot.news.items[0]).not.toHaveProperty("is_published");
    expect(snapshot.news_detail["release-2026-10"]).not.toHaveProperty("visible_from");
    expect(snapshot.static_pages[0]).not.toHaveProperty("id");
    expect(snapshot.static_pages[0]).toMatchObject({ slug: "guide", sort_order: 1 });
  });

  it("carries the release id the API actually emits", () => {
    const snapshot = normalizeContentSnapshot(rawSnapshot({ release_id: 7 }));
    expect(snapshot.release_id).toBe(7);
    expect(normalizeContentSnapshot(rawSnapshot())).not.toHaveProperty("release_id");
    expect(() => normalizeContentSnapshot(rawSnapshot({ release_id: "7" }))).toThrow(
      /release_id must be an integer/,
    );
  });

  it("rejects a slug that could escape the news directory", () => {
    for (const slug of ["../escape", "a/b", "..", "UPPER", "with space", "%2e%2e"]) {
      expect(() => assertSafeSlug(slug), slug).toThrow(/not a safe news slug/);
    }
    const escaping = rawSnapshot({
      news: {
        source_total: 1,
        included_total: 1,
        truncated: false,
        items: [newsItem({ slug: "../../etc/passwd" })],
      },
    });
    expect(() => normalizeContentSnapshot(escaping)).toThrow(/not a safe news slug/);
    expect(() => normalizeContentSnapshot(rawSnapshot({ news_detail: { "../x": null } }))).toThrow(
      /news_detail key is not a safe news slug/,
    );
  });

  it("rejects a detail whose slug contradicts its key", () => {
    expect(() =>
      normalizeContentSnapshot(
        rawSnapshot({
          news_detail: { "release-2026-10": newsDetail({ slug: "different-slug" }) },
        }),
      ),
    ).toThrow(/does not match its news_detail key/);
  });
});

describe("release pinning", () => {
  const snapshot = normalizeContentSnapshot(rawSnapshot({ release_id: 11 })) as PublicContentSnapshot;

  it("parses SOYMUTDB_RELEASE_ID like the release manifest does", () => {
    expect(resolveExpectedReleaseId("11")).toBe(11);
    expect(resolveExpectedReleaseId(undefined)).toBeUndefined();
    expect(resolveExpectedReleaseId("  ")).toBeUndefined();
    expect(() => resolveExpectedReleaseId("0")).toThrow(/positive integer/);
    expect(() => resolveExpectedReleaseId("release-11")).toThrow(/positive integer/);
  });

  it("rejects a payload that was not built for the pinned release", () => {
    expect(() => assertSnapshotRelease(snapshot, 11)).not.toThrow();
    expect(() => assertSnapshotRelease(snapshot, 12)).toThrow(/release_id mismatch/);
    const unpinned = normalizeContentSnapshot(rawSnapshot());
    expect(() => assertSnapshotRelease(unpinned, 11)).toThrow(/carries no release_id/);
    expect(() => assertSnapshotRelease(unpinned, undefined)).not.toThrow();
  });
});

describe("bootstrap serialisation", () => {
  const payload: BootstrapPayload = {
    page: "news-detail",
    slug: "x",
    generated_at: GENERATED_AT,
    data: {
      title_en: "</script><script>alert('xss')</script><!--",
      body: "a & b",
      lines: "one two three",
      nested: { closer: "</SCRIPT>" },
    },
  };

  it("cannot terminate its own script element", () => {
    const json = serializeBootstrap(payload);
    expect(json).not.toContain("<");
    expect(json).not.toContain(">");
    expect(json).not.toContain("&");
    expect(json).not.toContain(" ");
    expect(json).not.toContain(" ");
    expect(json).toContain("\\u003c/script\\u003e");
  });

  it("still parses as the exact payload the portal reads", () => {
    const parsed = JSON.parse(serializeBootstrap(payload)) as BootstrapPayload;
    expect(parsed).toEqual(payload);
    const tag = bootstrapScriptTag(payload);
    expect(tag.startsWith('<script type="application/json" id="rl-bootstrap">')).toBe(true);
    const inner = tag.slice(tag.indexOf(">") + 1, tag.lastIndexOf("</script>"));
    expect(JSON.parse(inner)).toEqual(payload);
  });
});

describe("document paths", () => {
  it("maps route paths onto the static-route directory convention", () => {
    expect(contentDocumentRelativePath("/about")).toBe("about/index.html");
    expect(contentDocumentRelativePath("/news")).toBe("news/index.html");
    expect(contentDocumentRelativePath("/news/release-2026-10/")).toBe("news/release-2026-10/index.html");
    expect(() => contentDocumentRelativePath("/news/../about")).toThrow(/unsafe route path/);
  });

  it("injects into the mount container the client takes over", () => {
    const html = injectStaticContent(SHELL, "<main>body</main>", bootstrapScriptTag({
      page: "about",
      data: {},
      generated_at: GENERATED_AT,
    }));
    expect(html).toContain('<div id="root"><main>body</main>');
    expect(html).toContain('id="rl-bootstrap"');
    // createRoot() clears #root: the static body must be inside it, not a
    // sibling that would still be on screen next to the React app.
    expect(html.indexOf("rl-bootstrap")).toBeGreaterThan(html.indexOf('</div>'));
    document.body.innerHTML = html;
    document.getElementById("root")!.replaceChildren();
    expect(readBootstrap()).toEqual({ page: "about", data: {}, generated_at: GENERATED_AT });
    document.body.replaceChildren();
  });

  it("refuses a shell with nowhere to inject", () => {
    expect(() => injectStaticContent("<html><head></head></html>", "<main/>", "")).toThrow(
      /no #root\/#app mount container/,
    );
    expect(() => injectStaticContent("<html><body></body></html>", "<main/>", "")).toThrow(
      /no #root\/#app mount container/,
    );
  });
});

describe("snapshot acquisition", () => {
  const externalEnv = {
    VITE_SITE_VARIANT: "external",
    SOYMUTDB_CONTENT_SNAPSHOT_URL: "https://api.external.soymutdb.test/api/v1/content/snapshot",
  } satisfies NodeJS.ProcessEnv;

  it("never reads an external snapshot for the internal variant", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(rawSnapshot()));
    const result = await acquireContentSnapshot({
      env: {
        ...externalEnv,
        VITE_SITE_VARIANT: "internal",
        SOYMUTDB_CONTENT_SNAPSHOT_FILE: "/definitely/not/read.json",
      },
      fetchImpl: fetchImpl as unknown as typeof fetch,
      readFile: () => {
        throw new Error("internal builds must not open the external snapshot file");
      },
    });
    expect(result.status).toBe("skipped");
    expect(result.reason).toBe("internal-variant");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("skips with an explicit reason when nothing is configured", async () => {
    const result = await acquireContentSnapshot({ env: { VITE_SITE_VARIANT: "external" } });
    expect(result).toMatchObject({ status: "skipped", reason: "not-configured" });
  });

  it("acquires a valid external snapshot from the URL", async () => {
    const result = await acquireContentSnapshot({
      env: externalEnv,
      fetchImpl: (async () => jsonResponse(rawSnapshot({ release_id: 5 }))) as typeof fetch,
    });
    expect(result.status).toBe("acquired");
    expect(result.source).toBe("url");
    expect(result.snapshot?.release_id).toBe(5);
    expect(result.snapshot?.site_variant).toBe("external");
  });

  it("fails closed in production when the configured URL cannot be used", async () => {
    const production = { ...externalEnv, CI: "true" };
    const cases: Array<[string, typeof fetch]> = [
      ["a non-2xx response", (async () => new Response("nope", { status: 503 })) as typeof fetch],
      [
        "a non-JSON content type",
        (async () =>
          new Response("<html>login</html>", {
            status: 200,
            headers: { "content-type": "text/html" },
          })) as typeof fetch,
      ],
      [
        "an oversized body",
        (async () =>
          jsonResponse({ ...rawSnapshot(), padding: "x".repeat(4096) })) as typeof fetch,
      ],
      ["an unknown schema", (async () => jsonResponse(rawSnapshot({ schema_version: 9 }))) as typeof fetch],
      [
        "an internal snapshot",
        (async () => jsonResponse(rawSnapshot({ site_variant: "internal" }))) as typeof fetch,
      ],
    ];
    for (const [label, fetchImpl] of cases) {
      await expect(
        acquireContentSnapshot({ env: production, fetchImpl, maxBytes: 2048 }),
        label,
      ).rejects.toThrow(/FATAL/);
    }
  });

  it("fails closed on a release mismatch from either source", async () => {
    const env = {
      VITE_SITE_VARIANT: "external",
      CI: "true",
      SOYMUTDB_RELEASE_ID: "9",
      SOYMUTDB_CONTENT_SNAPSHOT_URL: externalEnv.SOYMUTDB_CONTENT_SNAPSHOT_URL,
      SOYMUTDB_CONTENT_SNAPSHOT_FILE: "/tmp/snapshot.json",
    } satisfies NodeJS.ProcessEnv;
    await expect(
      acquireContentSnapshot({
        env,
        fetchImpl: (async () => jsonResponse(rawSnapshot({ release_id: 8 }))) as typeof fetch,
      }),
    ).rejects.toThrow(/release_id mismatch/);

    await expect(
      acquireContentSnapshot({
        env: { ...env, SOYMUTDB_CONTENT_SNAPSHOT_URL: "" },
        readFile: () => JSON.stringify(rawSnapshot()),
      }),
    ).rejects.toThrow(/carries no release_id/);

    await expect(
      acquireContentSnapshot({
        env: { ...env, SOYMUTDB_CONTENT_SNAPSHOT_URL: "" },
        readFile: () => JSON.stringify(rawSnapshot({ release_id: 4 })),
      }),
    ).rejects.toThrow(/release_id mismatch/);
  });

  it("accepts a fixture only when it is external and release-pinned", async () => {
    const result = await acquireContentSnapshot({
      env: {
        VITE_SITE_VARIANT: "external",
        SOYMUTDB_RELEASE_ID: "3",
        SOYMUTDB_CONTENT_SNAPSHOT_FILE: "/tmp/snapshot.json",
      },
      readFile: () => JSON.stringify(rawSnapshot({ release_id: 3 })),
    });
    expect(result).toMatchObject({ status: "acquired", source: "file", releaseId: 3 });
  });

  it("rejects a fixture that is not external even outside production", async () => {
    const result = await acquireContentSnapshot({
      env: {
        VITE_SITE_VARIANT: "external",
        SOYMUTDB_CONTENT_SNAPSHOT_FILE: "/tmp/snapshot.json",
      },
      readFile: () => JSON.stringify(rawSnapshot({ site_variant: "internal" })),
    });
    expect(result.status).toBe("skipped");
  });

  it("treats CI and production modes as fail-closed builds", () => {
    expect(isProductionBuild({ CI: "true" })).toBe(true);
    expect(isProductionBuild({ NODE_ENV: "production" })).toBe(true);
    expect(isProductionBuild({ VITE_DEPLOYMENT_MODE: "production" })).toBe(true);
    expect(isProductionBuild({ VITE_DEPLOYMENT_MODE: "demo" })).toBe(false);
    expect(resolveSiteVariant({})).toBe("external");
    expect(() => resolveSiteVariant({ VITE_SITE_VARIANT: "staging" })).toThrow(/must be "external" or "internal"/);
  });
});

describe("content document rendering", () => {
  const runtime = () => createBuildRuntime();
  const env = { VITE_SITE_VARIANT: "external" } satisfies NodeJS.ProcessEnv;

  it("plans a real body and bootstrap for every generatable page", () => {
    const snapshot = normalizeContentSnapshot(rawSnapshot());
    const pages = planContentPages(snapshot, runtime());
    const routes = pages.map((page) => page.routePath);
    expect(routes).toContain("/about");
    expect(routes).toContain("/publications");
    expect(routes).toContain("/news");
    expect(routes).toContain("/news/release-2026-10");
    // The visibility-window article is listed but never statically generated.
    expect(routes).not.toContain("/news/withdrawn-article");

    const about = pages.find((page) => page.kind === "about");
    expect(about?.mainHtml).toContain("<main");
    expect(about?.mainHtml).toContain("About body.");
    expect(about?.bootstrap.page).toBe("about");
  });

  it("sanitises richtext at build time", () => {
    const snapshot = normalizeContentSnapshot(
      rawSnapshot({
        about: {
          title_en: "About",
          title_zh: null,
          summary_en: null,
          summary_zh: null,
          content_en:
            '<p onclick="steal()">ok</p><script>alert(1)</script><img src=x onerror="alert(2)">',
          content_zh: null,
        },
      }),
    );
    const about = planContentPages(snapshot, runtime()).find((page) => page.kind === "about");
    expect(about?.mainHtml).toContain("ok");
    expect(about?.mainHtml).not.toContain("<script");
    expect(about?.mainHtml).not.toContain("onclick");
    expect(about?.mainHtml).not.toContain("onerror");
  });

  it("writes content-bearing documents and skips the window article", () => {
    distDir = makeDist();
    const report = buildContentDocuments({ env, runtime: runtime(), distDir });
    expect(report.status).toBe("written");
    expect(report.documents.sort()).toEqual([
      "about/index.html",
      "news/index.html",
      "news/release-2026-10/index.html",
      "publications/index.html",
    ]);

    const about = readFileSync(join(distDir, "about/index.html"), "utf8");
    // Real content in <main>, not a <noscript> fallback or a head-only hint.
    expect(about).toMatch(/<main[^>]*>[\s\S]*About body\.[\s\S]*<\/main>/);
    expect(about).toContain('<script type="application/json" id="rl-bootstrap">');
    expect(about).toContain("About SoyMutDB");
    expect(about).not.toContain("<noscript>");

    const detail = readFileSync(join(distDir, "news/release-2026-10/index.html"), "utf8");
    expect(detail).toContain("Body copy for the release.");
    expect(detail).toContain('"page":"news-detail"');

    const list = readFileSync(join(distDir, "news/index.html"), "utf8");
    expect(list).toContain('href="/news/release-2026-10/"');
    expect(list).toContain('href="/news/withdrawn-article/"');
  });

  it("removes a document left behind for a withdrawn article", () => {
    distDir = makeDist();
    mkdirSync(join(distDir, "news/withdrawn-article"), { recursive: true });
    writeFileSync(join(distDir, "news/withdrawn-article/index.html"), "<html>stale</html>", "utf8");

    const report = buildContentDocuments({ env, runtime: runtime(), distDir });
    expect(report.removed).toContain("news/withdrawn-article/index.html");
    expect(() => readFileSync(join(distDir, "news/withdrawn-article/index.html"), "utf8")).toThrow();
  });

  it("uses the deployment prefix for news links, canonical URLs and sitemap entries", () => {
    distDir = makeDist();
    buildContentDocuments({
      env: { ...env, VITE_BASE_URL: "/database/", SOYMUTDB_SITE_URL: "https://example.test" },
      runtime: runtime(), distDir,
    });
    const list = readFileSync(join(distDir, "news/index.html"), "utf8");
    expect(list).toContain('href="/database/news/release-2026-10/"');
    const detail = readFileSync(join(distDir, "news/release-2026-10/index.html"), "utf8");
    expect(detail).toContain('href="https://example.test/database/news/release-2026-10"');
    const sitemap = readFileSync(join(distDir, "sitemap.xml"), "utf8");
    expect(sitemap).toContain("https://example.test/database/news/release-2026-10");
    expect(sitemap).not.toContain("withdrawn-article");
  });

  it("writes nothing at all for the internal variant", () => {
    distDir = makeDist();
    const report = buildContentDocuments({
      env: { ...env, VITE_SITE_VARIANT: "internal" },
      runtime: runtime(),
      distDir,
    });
    expect(report).toMatchObject({ status: "skipped", reason: "internal-variant", documents: [] });
    expect(readFileSync(join(distDir, "index.html"), "utf8")).toBe(SHELL);
    expect(() => readFileSync(join(distDir, "about/index.html"), "utf8")).toThrow();
  });

  it("removes a previously generated article absent from the next snapshot", () => {
    distDir = makeDist();
    buildContentDocuments({ env, runtime: runtime(), distDir });
    const stale = join(distDir, "news/release-2026-10/index.html");
    writeFileSync(`${stale}.gz`, "stale gzip");
    writeFileSync(join(distDir, "data/content.json"), JSON.stringify(rawSnapshot({
      news: { source_total: 0, included_total: 0, truncated: false, items: [] },
      news_detail: {},
    })));
    const report = buildContentDocuments({ env, runtime: runtime(), distDir });
    expect(report.removed).toContain("news/release-2026-10/index.html");
    expect(() => readFileSync(stale)).toThrow();
    expect(() => readFileSync(`${stale}.gz`)).toThrow();
  });

  it("rejects unsafe document ownership metadata before replacing pages", () => {
    distDir = makeDist();
    writeFileSync(join(distDir, "data/content-documents.json"), JSON.stringify(["../../outside.html"]));
    expect(() => buildContentDocuments({ env, runtime: runtime(), distDir })).toThrow(
      /invalid generated-document manifest/,
    );
    expect(() => readFileSync(join(distDir, "about/index.html"))).toThrow();
  });

  it("skips when the build produced no snapshot", () => {
    distDir = mkdtempSync(join(tmpdir(), "rl-content-empty-"));
    writeFileSync(join(distDir, "index.html"), SHELL, "utf8");
    const report = buildContentDocuments({ env, runtime: runtime(), distDir });
    expect(report).toMatchObject({ status: "skipped", reason: "no-snapshot" });
  });

  it("refuses to render a snapshot built for another release", () => {
    distDir = makeDist(rawSnapshot({ release_id: 2 }));
    expect(() =>
      buildContentDocuments({
        env: { ...env, SOYMUTDB_RELEASE_ID: "3" },
        runtime: runtime(),
        distDir,
      }),
    ).toThrow(/release_id mismatch/);
  });

  it("refuses to render an internal snapshot that reached the tree", () => {
    distDir = makeDist(rawSnapshot({ site_variant: "internal" }));
    expect(() => buildContentDocuments({ env, runtime: runtime(), distDir })).toThrow(
      /site_variant must be "external"/,
    );
  });
});
