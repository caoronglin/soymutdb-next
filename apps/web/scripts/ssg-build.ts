#!/usr/bin/env tsx
/**
 * SSG Build Script
 *
 * Generates static HTML pages for SoyMutDB by:
 *   1. Fetching page layouts from /api/v1/layout/{page} (or using fallback data)
 *   2. Fetching static/cacheable widgets and inlining their HTML
 *   3. Leaving dynamic widgets as placeholders (data-widget attributes)
 *   4. Assembling complete pages via base-template.ts
 *   5. Writing to dist/{page}.html
 *
 * If the API server is unreachable, falls back to embedded data so the
 * build succeeds even in CI / offline environments.
 */

import { writeFileSync, mkdirSync, existsSync, copyFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { renderBaseTemplate, discoverAssets, renderRedirectTemplate } from "./base-template";
import { FALLBACK_PAGES, type PageLayout, type WidgetLayout } from "./fallback-data";

/* ------------------------------------------------------------------ */
/*  Configuration                                                     */
/* ------------------------------------------------------------------ */

const API_BASE = process.env.SOYMUTDB_API_URL ?? "http://localhost:8000";
const DIST_DIR = join(process.cwd(), "dist");
const PAGES = [
    "index",
    "about",
    "browser",
    "guide",
    "downloads",
    "publications",
    "help",
    "sra",
    "compare",
];

// Request timeout for API calls (ms)
const FETCH_TIMEOUT = Number(process.env.SOYMUTDB_FETCH_TIMEOUT ?? 5000);

/* ------------------------------------------------------------------ */
/*  HTTP helpers                                                      */
/* ------------------------------------------------------------------ */

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T | null> {
    try {
        const res = await fetch(url, {
            headers: { Accept: "application/json" },
            signal,
        });
        if (!res.ok) return null;
        return (await res.json()) as T;
    } catch {
        return null;
    }
}

async function fetchHtml(url: string, signal?: AbortSignal): Promise<string | null> {
    try {
        const res = await fetch(url, {
            headers: { Accept: "text/html" },
            signal,
        });
        if (!res.ok) return null;
        return await res.text();
    } catch {
        return null;
    }
}

/** Fetch JSON with a timeout. */
async function fetchWithTimeout<T>(
    url: string,
    isHtml = false,
): Promise<T | string | null> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT);
    try {
        return isHtml
            ? await fetchHtml(url, ctrl.signal)
            : await fetchJson<T>(url, ctrl.signal);
    } finally {
        clearTimeout(timer);
    }
}

/* ------------------------------------------------------------------ */
/*  API availability check                                            */
/* ------------------------------------------------------------------ */

async function isApiAvailable(): Promise<boolean> {
    try {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT);
        const res = await fetch(`${API_BASE}/api/v1/health`, { signal: ctrl.signal });
        clearTimeout(timer);
        return res.ok;
    } catch {
        return false;
    }
}

/* ------------------------------------------------------------------ */
/*  Widget rendering                                                  */
/* ------------------------------------------------------------------ */

/**
 * Determine whether a widget should be inlined (static/cached) or left
 * as a dynamic placeholder.
 */
function shouldInlineWidget(w: WidgetLayout): boolean {
    return w.data_source === "static" || w.cache_ttl > 0;
}

/** Render a placeholder div for dynamic widgets. */
function renderWidgetPlaceholder(w: WidgetLayout): string {
    const paramsAttr = w.params
        ? ` data-widget-params='${JSON.stringify(w.params)}'`
        : "";
    return `<div data-widget="${w.name}"${paramsAttr} class="widget-placeholder" style="min-height:2rem;display:flex;align-items:center;justify-content:center;color:#999;font-size:0.875rem">Loading ${w.name}…</div>`;
}

/**
 * For a single widget, either:
 *   - Fetch and return its HTML (if inlinable and API available)
 *   - Return fallback_html (if inlinable and API unavailable)
 *   - Return a placeholder div (if dynamic)
 */
async function resolveWidgetHtml(w: WidgetLayout, useFallback: boolean): Promise<string> {
    if (!shouldInlineWidget(w)) {
        return renderWidgetPlaceholder(w);
    }

    if (!useFallback) {
        const url = `${API_BASE}/api/v1/widget/${w.name}${
            w.params ? `?params=${encodeURIComponent(JSON.stringify(w.params))}` : ""
        }`;
        const html = await fetchWithTimeout<string>(url, true);
        if (html && typeof html === "string") return html;
    }

    return w.fallback_html ?? renderWidgetPlaceholder(w);
}

/* ------------------------------------------------------------------ */
/*  Page layout resolution                                            */
/* ------------------------------------------------------------------ */

async function resolvePageLayout(page: string, useFallback: boolean): Promise<PageLayout> {
    if (!useFallback) {
        const layout = await fetchWithTimeout<PageLayout>(
            `${API_BASE}/api/v1/layout/${page}`,
        );
        if (layout && typeof layout === "object" && "widgets" in layout) {
            return layout as PageLayout;
        }
    }

    // Fallback
    const fb = FALLBACK_PAGES.find((p) => p.page === page);
    if (fb) return fb;

    // Ultimate fallback
    return {
        page,
        title: `${page} — SoyMutDB`,
        description: `SoyMutDB ${page} page.`,
        widgets: [],
    };
}

/** Preserve historical static URLs while /browser remains the canonical SPA route. */
function writeLegacyRedirect(from: string, to: string): void {
    const html = renderRedirectTemplate(to);
    writeFileSync(join(DIST_DIR, `${from}.html`), html, "utf8");
    const directory = join(DIST_DIR, from);
    mkdirSync(directory, { recursive: true });
    writeFileSync(join(directory, "index.html"), html, "utf8");
}

/* ------------------------------------------------------------------ */
/*  i18n data injection                                               */
/* ------------------------------------------------------------------ */

function buildI18nScript(): string {
    // Embed minimal i18n init data so server-rendered pages show correct language.
    // The full i18n module is loaded by the SPA bundle.
    return `<script>window.__soymutdb = window.__soymutdb || {}; window.__soymutdb.i18nReady = true;</script>`;
}

/* ------------------------------------------------------------------ */
/*  Main build                                                        */
/* ------------------------------------------------------------------ */

async function build() {
    console.log(`[ssg-build] API base: ${API_BASE}`);

    // Ensure dist exists
    if (!existsSync(DIST_DIR)) {
        mkdirSync(DIST_DIR, { recursive: true });
    }

    // Copy public files to dist (in case vite build hasn't been run or
    // ssg-build is invoked standalone).  Vite normally handles this, but
    // this makes the script self-sufficient.
    const PUBLIC_DIR = join(process.cwd(), "public");
    if (existsSync(PUBLIC_DIR)) {
        for (const f of readdirSync(PUBLIC_DIR)) {
            const src = join(PUBLIC_DIR, f);
            const dst = join(DIST_DIR, f);
            try {
                copyFileSync(src, dst);
            } catch {
                // Ignore (file may already exist)
            }
        }
    }

    const assets = discoverAssets();
    console.log(
        `[ssg-build] Discovered assets: js=${assets.jsEntry}, css=${assets.cssEntry}, preloads=${assets.preloads.length}, fonts=${assets.fontPreloads.length}`,
    );

    const apiAvailable = await isApiAvailable();
    const useFallback = !apiAvailable;
    if (useFallback) {
        console.warn(
            `[ssg-build] API at ${API_BASE} is not available — using embedded fallback data.`,
        );
    } else {
        console.log(`[ssg-build] API is available — fetching live widget data.`);
    }

    const i18nScript = buildI18nScript();

    for (const pageName of PAGES) {
        console.log(`[ssg-build] Building page: ${pageName}`);

        // The API/fallback layout key predates the public /browser route.
        const layoutPageName = pageName === "browser" ? "browse" : pageName;
        const layout = await resolvePageLayout(layoutPageName, useFallback);

        // Resolve all widgets for this page
        const widgetHtmls = await Promise.all(
            layout.widgets.map((w) => resolveWidgetHtml(w, useFallback)),
        );
        const widgetsHtml = widgetHtmls.join("\n    ");

        const html = renderBaseTemplate({
            title: layout.title,
            description: layout.description,
            lang: "en",
            widgetsHtml,
            bodyScripts: i18nScript,
            canonical:
                pageName === "index"
                    ? "https://soymutdb.org/"
                    : `https://soymutdb.org/${pageName}`,
            assets,
        });

        const outPath = join(DIST_DIR, `${pageName}.html`);
        writeFileSync(outPath, html, "utf8");
        console.log(`[ssg-build]   Wrote ${outPath} (${html.length} bytes)`);
    }

    writeLegacyRedirect("browse", "browser");

    // Ensure index.html is the SPA root too. Build-time markup remains in its
    // own container until the independently rendered React tree commits.
    const indexLayout = await resolvePageLayout("index", useFallback);
    const indexWidgetHtmls = await Promise.all(
        indexLayout.widgets.map((w) => resolveWidgetHtml(w, useFallback)),
    );
    const indexHtml = renderBaseTemplate({
        title: indexLayout.title,
        description: indexLayout.description,
        lang: "en",
        widgetsHtml: indexWidgetHtmls.join("\n    "),
        bodyScripts: i18nScript,
        canonical: "https://soymutdb.org/",
        assets,
    });
    writeFileSync(join(DIST_DIR, "index.html"), indexHtml, "utf8");
    console.log(`[ssg-build] Rewrote dist/index.html with static fallback content.`);

    console.log(`[ssg-build] Done. Built ${PAGES.length} pages to ${DIST_DIR}`);
}

build().catch((err) => {
    console.error("[ssg-build] Build failed:", err);
    process.exit(1);
});
