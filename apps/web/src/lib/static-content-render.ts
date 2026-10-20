/**
 * Pure build-time rendering for the public content snapshot.
 *
 * This module holds every decision the SSG content step makes about the
 * snapshot payload and the documents it produces, with no filesystem, network
 * or DOM dependency of its own:
 *
 *   - `normalizeContentSnapshot()` validates the payload against the *real*
 *     API contract (`apps/api/app/services/content_snapshot_service.py` and
 *     the response models in `apps/api/app/schemas/{news,content}.py`) and
 *     re-emits it through an explicit public whitelist, so an unknown or
 *     newly-added upstream field can never be copied into a published
 *     artifact by accident.
 *   - `planContentPages()` turns the validated snapshot into the set of route
 *     documents to write, each with a real `<main>` body and the
 *     `#rl-bootstrap` payload the portal already knows how to read.
 *   - `injectStaticContent()` writes the body into the built Umi shell.
 *
 * ## Relationship to the client render — NOT hydration
 *
 * The emitted documents are a *pre-rendered public body* served to crawlers
 * and no-JS clients. They are not `hydrateRoot` output: the portal boots with
 * `createRoot`, which clears the mount container and renders the React tree,
 * so on a JS-capable client the static body is **replaced** rather than
 * hydrated. Turning that replacement into real hydration (the same component
 * tree rendering the same markup on both sides, then `hydrateRoot`) is a
 * follow-up that owns `src/routes/*` and the app entry; this build step does
 * not and cannot own it. The static body is therefore injected *inside* the
 * mount container: it is the content of the node React takes over, not a
 * sibling that would end up duplicated next to the app.
 *
 * Richtext is never trusted here: the caller must pass a real sanitizer
 * (DOMPurify bound to a jsdom window, see `scripts/content-snapshot-build.ts`).
 * There is deliberately no regex-based tag stripping anywhere in this file.
 */

import { escapeHtml as escapeHtmlText } from "./static-routes";

/** Snapshot schema this build understands. Anything else is rejected. */
export const CONTENT_SNAPSHOT_SCHEMA_VERSION = 2;

/** Slug shape accepted for a news document path (API `NewsCreate.slug`). */
export const NEWS_SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** Upper bound on generated news detail documents (matches the API cap). */
export const DEFAULT_MAX_NEWS_DETAIL_PAGES = 500;

export interface PublicNewsSummary {
  slug: string;
  title_en: string;
  title_zh: string | null;
  category: string | null;
  cover_url: string | null;
  cover_alt_text: string | null;
  cover_asset_id: string | null;
  featured_sort: number;
  carousel_group: string | null;
  carousel_sort: number;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PublicNewsDetail extends PublicNewsSummary {
  content_en: string;
  content_zh: string | null;
  source_platform: string | null;
  source_url: string | null;
  source_published_at: string | null;
  source_synced_at: string | null;
}

export interface PublicAbout {
  title_en: string | null;
  title_zh: string | null;
  summary_en: string | null;
  summary_zh: string | null;
  content_en: string | null;
  content_zh: string | null;
}

export interface PublicPublication {
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

export interface PublicStaticPage {
  slug: string;
  title_en: string;
  title_zh: string | null;
  content_en: string;
  content_zh: string | null;
  summary: string | null;
  category: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

/** The whitelisted, publishable shape written to `data/content.json`. */
export interface PublicContentSnapshot {
  schema_version: number;
  generated_at: string;
  site_variant: "external";
  /** Present only when the API built a release-pinned snapshot. */
  release_id?: number;
  news: {
    source_total: number;
    included_total: number;
    truncated: boolean;
    items: PublicNewsSummary[];
  };
  /** Slug -> detail. `null` marks a visibility-window article: never static. */
  news_detail: Record<string, PublicNewsDetail | null>;
  about: PublicAbout | null;
  publications: PublicPublication[];
  static_pages: PublicStaticPage[];
}

/** Per-page payload embedded as `<script type="application/json" id="rl-bootstrap">`. */
export interface BootstrapPayload {
  page: "news-list" | "news-detail" | "about" | "publications-list";
  category?: string;
  slug?: string;
  data: unknown;
  generated_at: string;
}

export type ContentPageKind = "about" | "publications" | "news-list" | "news-detail";

export interface ContentPage {
  /** Router path, e.g. `/about` or `/news/<slug>`. */
  routePath: string;
  title: string;
  description?: string;
  /** Assembled and build-sanitised `<main>` fragment. */
  mainHtml: string;
  bootstrap: BootstrapPayload;
  kind: ContentPageKind;
}

export interface RenderDependencies {
  /** Normalized deployment prefix, e.g. / or /soymutdb/. */
  basePath?: string;
  /** DOMPurify-backed sanitizer. Required — there is no regex fallback. */
  sanitizeHtml: (html: string) => string;
  /** jsdom-backed HTML -> text, used for meta descriptions only. */
  htmlToText: (html: string) => string;
}

export class SnapshotValidationError extends Error {
  constructor(message: string) {
    super(`[content-snapshot] ${message}`);
    this.name = "SnapshotValidationError";
  }
}

/* -------------------------------------------------------------------------- */
/* Validation primitives                                                       */
/* -------------------------------------------------------------------------- */

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new SnapshotValidationError(`${path} must be a non-empty string`);
  }
  return value;
}

function optionalString(value: unknown, path: string): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string") {
    throw new SnapshotValidationError(`${path} must be a string or null`);
  }
  return value;
}

function optionalNumber(value: unknown, path: string, fallback: number): number {
  if (value === undefined || value === null) return fallback;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new SnapshotValidationError(`${path} must be a finite number`);
  }
  return value;
}

function nullableNumber(value: unknown, path: string): number | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new SnapshotValidationError(`${path} must be a finite number or null`);
  }
  return value;
}

function optionalBoolean(value: unknown, path: string, fallback: boolean): boolean {
  if (value === undefined || value === null) return fallback;
  if (typeof value !== "boolean") {
    throw new SnapshotValidationError(`${path} must be a boolean`);
  }
  return value;
}

function requireBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new SnapshotValidationError(`${path} must be a boolean`);
  }
  return value;
}

function requireInteger(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    throw new SnapshotValidationError(`${path} must be an integer`);
  }
  return value;
}

/**
 * Reject any slug that could escape the news directory. Path safety is a
 * build-time gate, not a runtime one: `../x`, `a/b`, absolute paths, Windows
 * separators and URL-encoded separators all fail here.
 */
export function assertSafeSlug(slug: unknown, path = "slug"): string {
  if (typeof slug !== "string" || !NEWS_SLUG_PATTERN.test(slug)) {
    throw new SnapshotValidationError(
      `${path} is not a safe news slug (${JSON.stringify(slug)})`,
    );
  }
  return slug;
}

/* -------------------------------------------------------------------------- */
/* Whitelist normalisation                                                     */
/* -------------------------------------------------------------------------- */

function normalizeNewsSummary(raw: unknown, path: string): PublicNewsSummary {
  if (!isPlainObject(raw)) throw new SnapshotValidationError(`${path} must be an object`);
  return {
    slug: assertSafeSlug(raw.slug, `${path}.slug`),
    title_en: requireString(raw.title_en, `${path}.title_en`),
    title_zh: optionalString(raw.title_zh, `${path}.title_zh`),
    category: optionalString(raw.category, `${path}.category`),
    cover_url: optionalString(raw.cover_url, `${path}.cover_url`),
    cover_alt_text: optionalString(raw.cover_alt_text, `${path}.cover_alt_text`),
    cover_asset_id: optionalString(raw.cover_asset_id, `${path}.cover_asset_id`),
    featured_sort: optionalNumber(raw.featured_sort, `${path}.featured_sort`, 0),
    carousel_group: optionalString(raw.carousel_group, `${path}.carousel_group`),
    carousel_sort: optionalNumber(raw.carousel_sort, `${path}.carousel_sort`, 0),
    published_at: optionalString(raw.published_at, `${path}.published_at`),
    created_at: requireString(raw.created_at, `${path}.created_at`),
    updated_at: requireString(raw.updated_at, `${path}.updated_at`),
  };
}

function normalizeNewsDetail(
  raw: unknown,
  path: string,
  expectedSlug: string,
): PublicNewsDetail {
  if (!isPlainObject(raw)) {
    throw new SnapshotValidationError(`${path} must be an object`);
  }
  const summary = normalizeNewsSummary(raw, path);
  if (summary.slug !== expectedSlug) {
    throw new SnapshotValidationError(
      `${path}.slug (${summary.slug}) does not match its news_detail key (${expectedSlug})`,
    );
  }
  return {
    ...summary,
    content_en: requireString(raw.content_en, `${path}.content_en`),
    content_zh: optionalString(raw.content_zh, `${path}.content_zh`),
    source_platform: optionalString(raw.source_platform, `${path}.source_platform`),
    source_url: optionalString(raw.source_url, `${path}.source_url`),
    source_published_at: optionalString(raw.source_published_at, `${path}.source_published_at`),
    source_synced_at: optionalString(raw.source_synced_at, `${path}.source_synced_at`),
  };
}

function normalizeAbout(raw: unknown): PublicAbout | null {
  if (raw === undefined || raw === null) return null;
  if (!isPlainObject(raw)) {
    throw new SnapshotValidationError("about must be an object or null");
  }
  return {
    title_en: optionalString(raw.title_en, "about.title_en"),
    title_zh: optionalString(raw.title_zh, "about.title_zh"),
    summary_en: optionalString(raw.summary_en, "about.summary_en"),
    summary_zh: optionalString(raw.summary_zh, "about.summary_zh"),
    content_en: optionalString(raw.content_en, "about.content_en"),
    content_zh: optionalString(raw.content_zh, "about.content_zh"),
  };
}

function normalizePublication(raw: unknown, path: string): PublicPublication {
  if (!isPlainObject(raw)) throw new SnapshotValidationError(`${path} must be an object`);
  return {
    title: requireString(raw.title, `${path}.title`),
    title_zh: optionalString(raw.title_zh, `${path}.title_zh`),
    authors: requireString(raw.authors, `${path}.authors`),
    authors_zh: optionalString(raw.authors_zh, `${path}.authors_zh`),
    journal: optionalString(raw.journal, `${path}.journal`),
    year: nullableNumber(raw.year, `${path}.year`),
    doi: optionalString(raw.doi, `${path}.doi`),
    pmid: optionalString(raw.pmid, `${path}.pmid`),
    abstract: optionalString(raw.abstract, `${path}.abstract`),
    abstract_zh: optionalString(raw.abstract_zh, `${path}.abstract_zh`),
    is_featured: optionalBoolean(raw.is_featured, `${path}.is_featured`, false),
    created_at: requireString(raw.created_at, `${path}.created_at`),
  };
}

function normalizeStaticPage(raw: unknown, path: string): PublicStaticPage {
  if (!isPlainObject(raw)) throw new SnapshotValidationError(`${path} must be an object`);
  return {
    slug: assertSafeSlug(raw.slug, `${path}.slug`),
    title_en: requireString(raw.title_en, `${path}.title_en`),
    title_zh: optionalString(raw.title_zh, `${path}.title_zh`),
    content_en: requireString(raw.content_en, `${path}.content_en`),
    content_zh: optionalString(raw.content_zh, `${path}.content_zh`),
    summary: optionalString(raw.summary, `${path}.summary`),
    category: optionalString(raw.category, `${path}.category`),
    sort_order: optionalNumber(raw.sort_order, `${path}.sort_order`, 0),
    created_at: requireString(raw.created_at, `${path}.created_at`),
    updated_at: requireString(raw.updated_at, `${path}.updated_at`),
  };
}

/**
 * Validate a raw snapshot and re-emit it through the public whitelist.
 *
 * Rejections (fail-closed, never a partial page set):
 *   - any `schema_version` other than {@link CONTENT_SNAPSHOT_SCHEMA_VERSION};
 *   - a missing `generated_at` or a malformed `news` / `news_detail` block;
 *   - `site_variant` that is not exactly `"external"` — the internal variant
 *     never reads this payload, and an internal snapshot must never be
 *     published into the external artifact;
 *   - a slug that is not path-safe, or a `news_detail` key/slug mismatch;
 *   - a field the whitelist requires but the payload has with the wrong type.
 *
 * Fields outside the whitelist (`id`, `status`, `is_published`,
 * `visible_from`, `visible_to`, and anything a future API adds) are dropped
 * rather than copied: the published artifact carries exactly the public DTO
 * surface verified against `apps/api/app/schemas/{news,content}.py`. The
 * persistence key (`id`) is excluded on purpose — the API's own snapshot
 * service already leaves it out of publications, and no portal consumer reads
 * it.
 */
export function normalizeContentSnapshot(raw: unknown): PublicContentSnapshot {
  if (!isPlainObject(raw)) {
    throw new SnapshotValidationError("snapshot must be a JSON object");
  }
  if (raw.schema_version !== CONTENT_SNAPSHOT_SCHEMA_VERSION) {
    throw new SnapshotValidationError(
      `unsupported schema_version ${JSON.stringify(raw.schema_version)}; ` +
        `this build understands ${CONTENT_SNAPSHOT_SCHEMA_VERSION}`,
    );
  }
  if (raw.site_variant !== "external") {
    throw new SnapshotValidationError(
      `snapshot site_variant must be "external", got ${JSON.stringify(raw.site_variant)}`,
    );
  }
  const generatedAt = requireString(raw.generated_at, "generated_at");
  if (Number.isNaN(new Date(generatedAt).getTime())) {
    throw new SnapshotValidationError(
      `generated_at is not a valid timestamp: ${generatedAt}`,
    );
  }

  if (!isPlainObject(raw.news)) throw new SnapshotValidationError("news block is missing");
  if (!Array.isArray(raw.news.items)) {
    throw new SnapshotValidationError("news.items must be an array");
  }
  const items = raw.news.items.map((item, index) =>
    normalizeNewsSummary(item, `news.items[${index}]`),
  );

  if (!isPlainObject(raw.news_detail)) {
    throw new SnapshotValidationError("news_detail must be an object");
  }
  const newsDetail: Record<string, PublicNewsDetail | null> = {};
  for (const [key, value] of Object.entries(raw.news_detail)) {
    const slug = assertSafeSlug(key, "news_detail key");
    newsDetail[slug] =
      value === null ? null : normalizeNewsDetail(value, `news_detail[${key}]`, slug);
  }

  const publications = Array.isArray(raw.publications)
    ? raw.publications.map((item, index) =>
        normalizePublication(item, `publications[${index}]`),
      )
    : [];
  const staticPages = Array.isArray(raw.static_pages)
    ? raw.static_pages.map((item, index) =>
        normalizeStaticPage(item, `static_pages[${index}]`),
      )
    : [];

  const snapshot: PublicContentSnapshot = {
    schema_version: CONTENT_SNAPSHOT_SCHEMA_VERSION,
    generated_at: generatedAt,
    site_variant: "external",
    news: {
      source_total: requireInteger(raw.news.source_total, "news.source_total"),
      included_total: requireInteger(raw.news.included_total, "news.included_total"),
      truncated: requireBoolean(raw.news.truncated, "news.truncated"),
      items,
    },
    news_detail: newsDetail,
    about: normalizeAbout(raw.about),
    publications,
    static_pages: staticPages,
  };

  // `release_id` is an optional extra in the real API payload:
  // ContentSnapshotService.build_snapshot adds it only for a release-pinned
  // request (an int query parameter). Carried through when present, rejected
  // when malformed.
  if (raw.release_id !== undefined && raw.release_id !== null) {
    snapshot.release_id = requireInteger(raw.release_id, "release_id");
  }
  return snapshot;
}

/** Parse `SOYMUTDB_RELEASE_ID` (same contract as `release-manifest.ts`). */
export function resolveExpectedReleaseId(raw: string | undefined): number | undefined {
  const value = raw?.trim();
  if (!value) return undefined;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new SnapshotValidationError(
      `SOYMUTDB_RELEASE_ID must be a positive integer: ${JSON.stringify(value)}`,
    );
  }
  return parsed;
}

/**
 * Require a release-pinned payload when the build pins a release. A snapshot
 * built for the mutable active-release alias does not describe the tree this
 * build produces, so publishing it would put another release's content in this
 * artifact.
 */
export function assertSnapshotRelease(
  snapshot: PublicContentSnapshot,
  expectedReleaseId: number | undefined,
): void {
  if (expectedReleaseId === undefined) return;
  if (snapshot.release_id === undefined) {
    throw new SnapshotValidationError(
      `the build pins release_id=${expectedReleaseId} but the snapshot carries no ` +
        "release_id (it was fetched without ?release_id=); refusing to publish content " +
        "from an unpinned snapshot",
    );
  }
  if (snapshot.release_id !== expectedReleaseId) {
    throw new SnapshotValidationError(
      `release_id mismatch: build pins ${expectedReleaseId}, snapshot carries ` +
        `${snapshot.release_id}`,
    );
  }
}

/* -------------------------------------------------------------------------- */
/* Bootstrap serialisation                                                     */
/* -------------------------------------------------------------------------- */

export const BOOTSTRAP_SCRIPT_ID = "rl-bootstrap";

/**
 * Serialise a bootstrap payload so it cannot terminate its own `<script>`.
 *
 * `JSON.stringify` output is legal JSON but not legal *HTML script text*:
 * `</script>` inside any string closes the element, and U+2028/U+2029 are
 * valid JSON yet illegal raw in a JavaScript string literal. Escaping `<`,
 * `>`, `&` and both line separators as `\uXXXX` keeps the text parseable as
 * JSON (so `JSON.parse(el.textContent)` keeps working unchanged) while
 * removing every sequence the HTML parser could act on.
 */
export function serializeBootstrap(payload: BootstrapPayload): string {
  return JSON.stringify(payload)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

export function bootstrapScriptTag(payload: BootstrapPayload): string {
  return (
    `<script type="application/json" id="${BOOTSTRAP_SCRIPT_ID}">` +
    `${serializeBootstrap(payload)}</script>`
  );
}

/* -------------------------------------------------------------------------- */
/* Page planning                                                               */
/* -------------------------------------------------------------------------- */

/** `/news/<slug>` -> `news/<slug>/index.html`, matching `static-routes`. */
export function contentDocumentRelativePath(routePath: string): string {
  const trimmed = routePath.replace(/^\/+|\/+$/g, "");
  if (!trimmed) throw new SnapshotValidationError(`empty route path: ${routePath}`);
  if (trimmed.split("/").some((segment) => segment === "." || segment === "..")) {
    throw new SnapshotValidationError(`unsafe route path: ${routePath}`);
  }
  return `${trimmed}/index.html`;
}

function truncate(text: string, max = 160): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > max ? `${collapsed.slice(0, max - 1)}…` : collapsed;
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toISOString().slice(0, 10);
}

function renderNewsList(
  snapshot: PublicContentSnapshot,
  deps: RenderDependencies,
): ContentPage {
  const items = snapshot.news.items;
  const cards = items
    .map((item) => {
      const heading = item.title_zh?.trim() ? item.title_zh : item.title_en;
      const category = item.category ? escapeHtmlText(item.category) : "";
      const published = formatDate(item.published_at);
      const alt = item.cover_alt_text ? escapeHtmlText(item.cover_alt_text) : "";
      const cover =
        item.cover_url && item.cover_url.trim()
          ? `<img class="rl-news-cover" src="${escapeHtmlText(item.cover_url)}" alt="${alt}" loading="lazy" />`
          : "";
      return [
        `<article class="rl-news-card">`,
        cover,
        `<h2><a href="${escapeHtmlText(deps.basePath ?? "/")}news/${escapeHtmlText(item.slug)}/">${escapeHtmlText(heading)}</a></h2>`,
        category ? `<p class="rl-news-category">${category}</p>` : "",
        published
          ? `<time datetime="${escapeHtmlText(item.published_at ?? "")}">${published}</time>`
          : "",
        "</article>",
      ]
        .filter(Boolean)
        .join("");
    })
    .join("\n");
  const more = snapshot.news.truncated
    ? `<p class="rl-news-more">The newest ${items.length} of ${snapshot.news.source_total} published articles are built statically; open the portal for the full archive.</p>`
    : "";
  const main = [
    '<main data-rl-static="content" class="container-prose">',
    "<h1>News — SoyMutDB</h1>",
    `<div class="rl-news-grid">\n${cards}\n</div>`,
    more,
    "</main>",
  ]
    .filter(Boolean)
    .join("\n");
  return {
    routePath: "/news",
    title: "News — SoyMutDB",
    description: "Announcements, updates, and news from the SoyMutDB project.",
    mainHtml: deps.sanitizeHtml(main),
    kind: "news-list",
    bootstrap: {
      page: "news-list",
      category: "all",
      data: {
        items,
        total: snapshot.news.source_total,
        page: 1,
        page_size: Math.max(items.length, 1),
      },
      generated_at: snapshot.generated_at,
    },
  };
}

function renderNewsDetail(
  detail: PublicNewsDetail,
  snapshot: PublicContentSnapshot,
  deps: RenderDependencies,
): ContentPage {
  const heading = detail.title_zh?.trim() ? detail.title_zh : detail.title_en;
  const body = deps.sanitizeHtml(detail.content_en);
  const description = truncate(deps.htmlToText(body));
  const published = formatDate(detail.published_at);
  const main = [
    '<main data-rl-static="content" class="container-prose">',
    `<h1>${escapeHtmlText(heading)}</h1>`,
    detail.category ? `<p class="rl-news-category">${escapeHtmlText(detail.category)}</p>` : "",
    published
      ? `<time datetime="${escapeHtmlText(detail.published_at ?? "")}">${published}</time>`
      : "",
    `<div class="rl-news-body">${body}</div>`,
    detail.source_url
      ? `<p class="rl-news-source"><a href="${escapeHtmlText(detail.source_url)}" rel="noopener noreferrer">Source</a></p>`
      : "",
    "</main>",
  ]
    .filter(Boolean)
    .join("\n");
  return {
    routePath: `/news/${detail.slug}`,
    title: `${heading} — SoyMutDB News`,
    description: description || undefined,
    mainHtml: deps.sanitizeHtml(main),
    kind: "news-detail",
    bootstrap: {
      page: "news-detail",
      slug: detail.slug,
      data: detail,
      generated_at: snapshot.generated_at,
    },
  };
}

function renderAbout(
  snapshot: PublicContentSnapshot,
  deps: RenderDependencies,
): ContentPage | null {
  const about = snapshot.about;
  if (!about) return null;
  const body = about.content_en ? deps.sanitizeHtml(about.content_en) : "";
  const summary = about.summary_en ? escapeHtmlText(about.summary_en) : "";
  if (!body.trim() && !summary.trim() && !about.title_en) return null;
  const heading = about.title_en?.trim() ? about.title_en : "About — SoyMutDB";
  const main = [
    '<main data-rl-static="content" class="container-prose">',
    `<h1>${escapeHtmlText(heading)}</h1>`,
    summary ? `<p class="rl-about-summary">${summary}</p>` : "",
    `<div class="rl-about-body">${body}</div>`,
    "</main>",
  ]
    .filter(Boolean)
    .join("\n");
  return {
    routePath: "/about",
    title: `${heading} — SoyMutDB`,
    description: truncate(deps.htmlToText(body || summary)) || undefined,
    mainHtml: deps.sanitizeHtml(main),
    kind: "about",
    bootstrap: {
      page: "about",
      data: about,
      generated_at: snapshot.generated_at,
    },
  };
}

function renderPublications(
  snapshot: PublicContentSnapshot,
  deps: RenderDependencies,
): ContentPage | null {
  if (snapshot.publications.length === 0) return null;
  const rows = snapshot.publications
    .map((publication) => {
      const doi = publication.doi
        ? `<a href="https://doi.org/${escapeHtmlText(publication.doi)}" rel="noopener noreferrer">DOI</a>`
        : "";
      const pmid = publication.pmid
        ? `<a href="https://pubmed.ncbi.nlm.nih.gov/${escapeHtmlText(publication.pmid)}/" rel="noopener noreferrer">PMID ${escapeHtmlText(publication.pmid)}</a>`
        : "";
      const venue = [
        publication.journal ? escapeHtmlText(publication.journal) : "",
        publication.year === null ? "" : String(publication.year),
      ]
        .filter(Boolean)
        .join(" ");
      return [
        "<li>",
        `<h2>${escapeHtmlText(publication.title)}</h2>`,
        `<p>${escapeHtmlText(publication.authors)}</p>`,
        venue ? `<p class="rl-publication-venue">${venue}</p>` : "",
        doi || pmid ? `<p class="rl-publication-links">${[doi, pmid].filter(Boolean).join(" ")}</p>` : "",
        "</li>",
      ]
        .filter(Boolean)
        .join("");
    })
    .join("\n");
  const main = [
    '<main data-rl-static="content" class="container-prose">',
    "<h1>Publications — SoyMutDB</h1>",
    `<ul class="rl-publication-list">\n${rows}\n</ul>`,
    "</main>",
  ].join("\n");
  return {
    routePath: "/publications",
    title: "Publications — SoyMutDB",
    description: "Publications citing or describing SoyMutDB.",
    mainHtml: deps.sanitizeHtml(main),
    kind: "publications",
    bootstrap: {
      page: "publications-list",
      data: snapshot.publications,
      generated_at: snapshot.generated_at,
    },
  };
}

export interface PlanOptions extends RenderDependencies {
  maxNewsDetailPages?: number;
}

/**
 * Build every content document for the external variant.
 *
 * Visibility-window articles (`news_detail[slug] === null`) are never
 * generated: the file would keep serving an article the API no longer
 * returns. Pages whose data is empty are skipped entirely, leaving the
 * `generate-static-routes` shell in place. Two pages mapping to the same
 * output path is a build error, never a silent overwrite.
 */
export function planContentPages(
  snapshot: PublicContentSnapshot,
  options: PlanOptions,
): ContentPage[] {
  const maxDetail = options.maxNewsDetailPages ?? DEFAULT_MAX_NEWS_DETAIL_PAGES;
  const pages: ContentPage[] = [];

  if (snapshot.news.items.length > 0) pages.push(renderNewsList(snapshot, options));
  const about = renderAbout(snapshot, options);
  if (about) pages.push(about);
  const publications = renderPublications(snapshot, options);
  if (publications) pages.push(publications);

  const detailPages: ContentPage[] = [];
  for (const detail of Object.values(snapshot.news_detail)) {
    if (detail === null) continue;
    detailPages.push(renderNewsDetail(detail, snapshot, options));
    if (detailPages.length >= maxDetail) break;
  }
  pages.push(...detailPages);

  const seen = new Map<string, ContentPageKind>();
  for (const page of pages) {
    const target = contentDocumentRelativePath(page.routePath);
    const previous = seen.get(target);
    if (previous !== undefined) {
      throw new SnapshotValidationError(
        `route collision: ${previous} and ${page.kind} both render ${target}`,
      );
    }
    seen.set(target, page.kind);
  }
  return pages;
}

/* -------------------------------------------------------------------------- */
/* Document assembly                                                           */
/* -------------------------------------------------------------------------- */

const MOUNT_CONTAINER_PATTERNS = [
  /<div\b[^>]*\bid=["']root["'][^>]*>\s*<\/div>/i,
  /<div\b[^>]*\bid=["']app["'][^>]*>\s*<\/div>/i,
];

/**
 * Write the static body and the bootstrap payload into the built shell's mount
 * container.
 *
 * The body goes *inside* `#root`/`#app` on purpose: the portal boots with
 * `createRoot`, which clears that node, so a JS-capable client sees the React
 * app replace the pre-rendered body instead of both at once. A shell without a
 * recognisable mount container is rejected — appending the body anywhere else
 * would either duplicate the content or orphan it.
 */
export function injectStaticContent(
  shell: string,
  bodyHtml: string,
  bootstrapJson: string,
): string {
  for (const pattern of MOUNT_CONTAINER_PATTERNS) {
    const match = pattern.exec(shell);
    if (!match) continue;
    const openTag = match[0].slice(0, match[0].indexOf(">") + 1);
    // Keep the payload outside the React mount: createRoot clears its children.
    const replacement = `${openTag}${bodyHtml}</div>\n${bootstrapJson}`;
    return (
      shell.slice(0, match.index) +
      replacement +
      shell.slice(match.index + match[0].length)
    );
  }
  throw new SnapshotValidationError(
    "built shell has no #root/#app mount container",
  );
}
