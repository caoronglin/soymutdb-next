#!/usr/bin/env tsx
/**
 * SSG Content Pages (E2-3)
 *
 * Generates static HTML for content pages from the snapshot JSON
 * (dist/data/content.json, produced by fetch-content-snapshot.ts):
 *
 *   /news/index.html          — list (categories, cards, pagination)
 *   /news/{slug}.html         — detail (only snapshot-window articles;
 *                               visibility-window articles are null in the
 *                               snapshot and are NEVER generated here)
 *   /about.html               — about content
 *
 * Each page embeds a `#rl-bootstrap` JSON payload consumed by the SPA
 * (E3: src/lib/content-snapshot.ts) to prefill the query cache.
 *
 * Runs AFTER ssg-build/generate-samples and BEFORE gzip-compress/gen-sw
 * (see package.json build chain).  Missing snapshot → skip (exit 0); the
 * existing legacy pages remain untouched.
 */

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import createDOMPurify from "dompurify";
// The SSG script runs via tsx and is kept outside the application typecheck.
import jsdomPkg from "jsdom";
import { renderBaseTemplate } from "./base-template";

const { JSDOM } = jsdomPkg as {
  JSDOM: new (html: string) => { window: unknown };
};

const SITE_VARIANT = (process.env.VITE_SITE_VARIANT ?? process.env.SOYMUTDB_SITE_VARIANT ?? "external").trim().toLowerCase();
if (SITE_VARIANT !== "external" && SITE_VARIANT !== "internal") {
  throw new Error(`Invalid site variant "${SITE_VARIANT}". Use external or internal.`);
}
const ROBOTS_POLICY = SITE_VARIANT === "internal" ? "noindex, nofollow, noarchive" : undefined;
const DIST_DIR = resolve(process.cwd(), process.env.SOYMUTDB_DIST_DIR ?? "dist");
const SNAPSHOT_FILE = join(DIST_DIR, "data", "content.json");
const NEWS_DIR = join(DIST_DIR, "news");
const PUBLICATIONS_DIR = join(DIST_DIR, "publications");
const PAGES_DIR = join(DIST_DIR, "pages");

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

interface Snapshot {
  schema_version: number;
  generated_at: string;
  news: {
    source_total: number;
    included_total: number;
    truncated: boolean;
    items: NewsItem[];
  };
  news_detail: Record<string, NewsDetail | null>;
  about: About | null;
  publications?: Publication[];
  static_pages: StaticPage[];
}

interface Publication {
  id: string;
  title: string;
  title_zh: string | null;
  authors: string;
  authors_zh: string | null;
  journal: string | null;
  year: number | null;
  doi: string | null;
  pmid: string | null;
  abstract: string | null;
  abstract_zh: string | null;
  is_featured: boolean;
  created_at: string;
}

interface StaticPage {
  id: string;
  slug: string;
  title_en: string;
  title_zh: string | null;
  content_en: string;
  content_zh: string | null;
  summary: string | null;
  category: string | null;
  sort_order: number;
}

interface NewsItem {
  slug: string;
  title_en: string;
  title_zh: string | null;
  category: string;
  cover_url: string | null;
  published_at: string;
  featured_sort: number;
  carousel_group: string | null;
  carousel_sort: number;
  is_published: boolean;
  updated_at: string;
}

interface NewsDetail extends NewsItem {
  content_en: string;
  content_zh: string | null;
}

interface About {
  title_en: string | null;
  title_zh: string | null;
  summary_en: string | null;
  summary_zh: string | null;
  content_en: string | null;
  content_zh: string | null;
}

/* ------------------------------------------------------------------ */
/*  Sanitisation (SSG-side re-clean; server bleach is primary)        */
/* ------------------------------------------------------------------ */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const window = new JSDOM("").window as any;
const DOMPurify = createDOMPurify(window);

function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
  });
}

function stripTags(html: string): string {
  return html
    .replace(/<[^>]*>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function truncate(text: string, max = 160): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/* ------------------------------------------------------------------ */
/*  Bootstrap embedding                                               */
/* ------------------------------------------------------------------ */

function embedBootstrap(payload: Record<string, unknown>): string {
  // \u003c escapes prevent </script> breakout inside JSON.
  const json = JSON.stringify(payload).replace(/</g, "\\u003c");
  return `<script type="application/json" id="rl-bootstrap">${json}</script>`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10);
}

/* ------------------------------------------------------------------ */
/*  Page builders                                                     */
/* ------------------------------------------------------------------ */

function renderNewsList(snapshot: Snapshot): string {
  const items = snapshot.news.items;
  const title = "News — SoyMutDB";
  const description = "SoyMutDB news, updates and announcements.";

  const cards = items
    .map((it) => {
      const titleText = it.title_zh ?? it.title_en;
      const safeCover = safeCoverUrl(it.cover_url);
      const safeSlug = validateSlug(it.slug);
      const cover = safeCover
        ? `<img class="news-card-cover" src="${escapeAttr(safeCover)}" alt="" loading="lazy" />`
        : "";
      const href = safeSlug ? `news/${safeSlug}.html` : "#";
      return `<a class="news-card" href="${href}">
        ${cover}
        <div class="news-card-body">
          <span class="news-card-cat">${escapeAttr(it.category)}</span>
          <h3>${escapeAttr(titleText)}</h3>
          <time>${formatDate(it.published_at)}</time>
        </div>
      </a>`;
    })
    .join("\n");

  const truncationNotice = snapshot.news.truncated
    ? `<p class="news-more">More articles available online — <a href="/news">open the portal</a>.</p>`
    : "";

  const bootstrap = embedBootstrap({
    page: "news-list",
    data: { items, total: snapshot.news.included_total },
    generated_at: snapshot.generated_at,
  });

  return renderBaseTemplate({
    title,
    description,
    widgetsHtml: `
      <div class="container-prose news-page">
        <header><p class="eyebrow">SoyMutDB</p><h1>News</h1></header>
        <div class="news-grid">${cards}</div>
        ${truncationNotice}
      </div>`,
    bodyScripts: bootstrap,
    robots: ROBOTS_POLICY,
  });
}

function renderNewsDetail(slug: string, detail: NewsDetail, snapshot: Snapshot): string {
  const titleText = detail.title_zh ?? detail.title_en;
  const title = `${titleText} — SoyMutDB News`;
  const description = truncate(stripTags(detail.content_en));
  const safeCover = safeCoverUrl(detail.cover_url);
  const cover = safeCover
    ? `<img class="news-cover" src="${escapeAttr(safeCover)}" alt="" />`
    : "";
  const bodyHtml = sanitizeHtml(detail.content_en);

  const bootstrap = embedBootstrap({
    page: "news-detail",
    slug,
    data: detail,
    generated_at: snapshot.generated_at,
  });

  return renderBaseTemplate({
    title,
    description,
    widgetsHtml: `
      <article class="container-prose news-detail">
        <header>
          <p class="eyebrow">${escapeAttr(detail.category)}</p>
          <h1>${escapeAttr(titleText)}</h1>
          <time>${formatDate(detail.published_at)}</time>
        </header>
        ${cover}
        <div class="news-body">${bodyHtml}</div>
      </article>`,
    bodyScripts: bootstrap,
    robots: ROBOTS_POLICY,
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "Article",
      headline: titleText,
      datePublished: detail.published_at,
      dateModified: detail.updated_at,
      description,
    },
  });
}

function renderAbout(snapshot: Snapshot): string | null {
  const about = snapshot.about;
  if (!about || (!about.content_en && !about.content_zh)) {
    return null;
  }
  const titleText = about.title_en ?? "About — SoyMutDB";
  const content = sanitizeHtml(about.content_en ?? "");

  const bootstrap = embedBootstrap({
    page: "about",
    data: about,
    generated_at: snapshot.generated_at,
  });

  return renderBaseTemplate({
    title: `${about.title_en ?? "About"} — SoyMutDB`,
    description: truncate(stripTags(about.content_en ?? "")),
    widgetsHtml: `
      <article class="container-prose about-page">
        <header><p class="eyebrow">SoyMutDB</p><h1>${escapeAttr(titleText)}</h1></header>
        <div class="about-body">${content}</div>
      </article>`,
    bodyScripts: bootstrap,
    robots: ROBOTS_POLICY,
  });
}

function renderPublications(snapshot: Snapshot): string | null {
  const items = snapshot.publications;
  if (!items) return null;
  const cards = items.map((item) => {
    const title = item.title_zh || item.title;
    const authors = item.authors_zh || item.authors;
    const doiHref = item.doi && item.doi.startsWith("10.")
      ? `https://doi.org/${encodeURIComponent(item.doi)}`
      : null;
    const doi = item.doi ? `DOI: ${item.doi}` : "";
    return `<article class="publication-card">
      <h2>${escapeAttr(title)}</h2>
      <p class="publication-authors">${escapeAttr(authors)}</p>
      <p class="publication-meta">${escapeAttr([item.journal, item.year, doi].filter(Boolean).join(" · "))}</p>
      ${doiHref ? `<a href="${escapeAttr(doiHref)}" rel="noopener noreferrer">View paper</a>` : ""}
    </article>`;
  }).join("\n");
  return renderBaseTemplate({
    title: "Publications — SoyMutDB",
    description: "Research publications citing SoyMutDB.",
    widgetsHtml: `<main class="container-prose publications-page"><header><p class="eyebrow">SoyMutDB</p><h1>Publications</h1></header><div class="publication-grid">${cards}</div></main>`,
    bodyScripts: embedBootstrap({ page: "publications-list", data: items, generated_at: snapshot.generated_at }),
    robots: ROBOTS_POLICY,
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "ItemList",
      itemListElement: items.map((item, index) => ({
        "@type": "ListItem",
        position: index + 1,
        name: item.title,
        url: item.doi?.startsWith("10.") ? `https://doi.org/${encodeURIComponent(item.doi)}` : undefined,
      })),
    },
  });
}
function escapeAttr(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** URL protocol allowlist for attribute interpolation (image src, links). */
const ALLOWED_URL_PROTOCOLS = new Set(["http:", "https:", "data:"]);

/** Validate a ``cover_url``: relative or http(s)/data only; reject javascript:. */
function safeCoverUrl(url: string | null): string | null {
  if (!url) return null;
  const trimmed = url.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("/") && !trimmed.startsWith("//")) return trimmed;
  try {
    const parsed = new URL(trimmed);
    if (!ALLOWED_URL_PROTOCOLS.has(parsed.protocol)) return null;
    return trimmed;
  } catch {
    return null;
  }
}

/** Validate a news slug against the safe ``[a-z0-9-]+`` pattern. */
function validateSlug(slug: string): string | null {
  return SLUG_RE.test(slug) ? slug : null;
}

function renderStaticPage(page: StaticPage, snapshot: Snapshot): string {
  const title = page.title_en || page.slug;
  const eyebrow = page.category ? "<p class=\"eyebrow\">" + escapeAttr(page.category) + "</p>" : "";
  const body = sanitizeHtml(page.content_en ?? "");
  return renderBaseTemplate({
    title: title + " — SoyMutDB",
    description: page.summary ?? truncate(stripTags(page.content_en ?? "")),
    widgetsHtml: "<article class=\"container-prose static-page\"><header>" + eyebrow + "<h1>" + escapeAttr(title) + "</h1></header><div class=\"static-page-body\">" + body + "</div></article>",
    bodyScripts: embedBootstrap({ page: "static-page", slug: page.slug, data: page, generated_at: snapshot.generated_at }),
    robots: ROBOTS_POLICY,
  });
}

/* ------------------------------------------------------------------ */
/*  Main                                                              */
/* ------------------------------------------------------------------ */

function main(): void {
  if (!existsSync(SNAPSHOT_FILE)) {
    console.warn(
      "[ssg-content] no dist/data/content.json — skipping content pages (SPA/API fallback)",
    );
    return;
  }

  let snapshot: Snapshot;
  try {
    snapshot = JSON.parse(readFileSync(SNAPSHOT_FILE, "utf-8")) as Snapshot;
  } catch (err) {
    console.error(`[ssg-content] invalid snapshot: ${(err as Error).message}`);
    return;
  }

  mkdirSync(NEWS_DIR, { recursive: true });
  // News list.
  const listHtml = renderNewsList(snapshot);
  writeFileSync(join(DIST_DIR, "news", "index.html"), listHtml);
  console.log(`[ssg-content] wrote news/index.html (${snapshot.news.items.length} items)`);

  // News details — ONLY snapshot-window articles (never null entries).
  let detailCount = 0;
  for (const [slug, detail] of Object.entries(snapshot.news_detail)) {
    if (!detail || !SLUG_RE.test(slug)) continue;
    const html = renderNewsDetail(slug, detail, snapshot);
    writeFileSync(join(NEWS_DIR, `${slug}.html`), html);
    detailCount += 1;
  }
  console.log(`[ssg-content] wrote ${detailCount} news detail pages`);

  // About (optional).
  const aboutHtml = renderAbout(snapshot);
  if (aboutHtml) {
    writeFileSync(join(DIST_DIR, "about.html"), aboutHtml);
    console.log("[ssg-content] wrote about.html");
  }

  // Publications are generated only when the snapshot carries the block; an
  // absent block keeps the SPA/API route as the explicit fallback.
  const publicationsHtml = renderPublications(snapshot);
  if (publicationsHtml) {
    mkdirSync(PUBLICATIONS_DIR, { recursive: true });
    writeFileSync(join(PUBLICATIONS_DIR, "index.html"), publicationsHtml);
    console.log(`[ssg-content] wrote publications/index.html (${snapshot.publications?.length ?? 0} items)`);
  }

  // Rebuild this managed subtree on every snapshot so unpublishing a page
  // removes its former public HTML rather than leaving stale content online.
  rmSync(PAGES_DIR, { recursive: true, force: true });
  let staticPageCount = 0;
  for (const page of snapshot.static_pages ?? []) {
    const slug = validateSlug(page.slug);
    if (!slug) {
      console.warn("[ssg-content] skipping StaticPage with unsafe slug: " + page.slug);
      continue;
    }
    const outputDir = join(PAGES_DIR, slug);
    mkdirSync(outputDir, { recursive: true });
    writeFileSync(join(outputDir, "index.html"), renderStaticPage(page, snapshot));
    staticPageCount += 1;
  }
  console.log("[ssg-content] wrote " + staticPageCount + " static pages");

  // Append content URLs to the existing sitemap.xml (written by
  // generate-samples.ts) so search engines discover the static pages.
  appendNewsToSitemap(snapshot);
}

function appendNewsToSitemap(snapshot: Snapshot): void {
  const sitemapPath = join(DIST_DIR, "sitemap.xml");
  if (!existsSync(sitemapPath)) {
    console.warn("[ssg-content] no sitemap.xml found — skipping sitemap update");
    return;
  }
  let sitemap = readFileSync(sitemapPath, "utf-8");
  const urls: string[] = [];
  const newsUrl = `${SITE_BASE}/news`;
  if (!sitemap.includes(`<loc>${newsUrl}</loc>`)) {
    urls.push(`<url><loc>${newsUrl}</loc><priority>0.6</priority></url>`);
    for (const slug of Object.keys(snapshot.news_detail)) {
      if (snapshot.news_detail[slug]) {
        urls.push(`<url><loc>${SITE_BASE}/news/${slug}</loc><priority>0.5</priority></url>`);
      }
    }
  }
  for (const page of snapshot.static_pages ?? []) {
    const slug = validateSlug(page.slug);
    if (!slug) continue;
    const pageUrl = SITE_BASE + "/pages/" + slug;
    if (!sitemap.includes("<loc>" + pageUrl + "</loc>")) {
      urls.push("<url><loc>" + pageUrl + "</loc><priority>0.5</priority></url>");
    }
  }
  const publicationsUrl = `${SITE_BASE}/publications`;
  if (snapshot.publications && !sitemap.includes(`<loc>${publicationsUrl}</loc>`)) {
    urls.push(`<url><loc>${publicationsUrl}</loc><priority>0.6</priority></url>`);
  }
  if (urls.length === 0) return;
  const urlsetEnd = sitemap.lastIndexOf("</urlset>");
  if (urlsetEnd === -1) return;
  sitemap = sitemap.slice(0, urlsetEnd) + urls.join("\n") + "\n" + sitemap.slice(urlsetEnd);
  writeFileSync(sitemapPath, sitemap, "utf-8");
  console.log(`[ssg-content] appended ${urls.length} content URLs to sitemap.xml`);
}
//: Site base for sitemap <loc> entries (env-configurable, defaults to root).
const SITE_BASE = (process.env.SOYMUTDB_SITE_URL ?? process.env.SITE_BASE_URL ?? "https://caoronglin.github.io/soymutdb-next").replace(/\/$/, "");

main();
