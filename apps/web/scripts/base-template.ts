/**
 * Base HTML template for SSG-rendered pages.
 *
 * Produces a complete HTML5 document with:
 *   - SEO meta tags (title, description, Open Graph)
 *   - Font preloads (Inter, Fraunces, JetBrains Mono from dist/assets)
 *   - Hashed CSS/JS asset links discovered from the Vite build manifest
 *   - Theme initialisation script (runs before paint to avoid FOUC)
 *   - Tracking pixel snippet (1x1 transparent GIF, no JS)
 *   - Widget-loader script with Trusted Types policy
 *   - Reduced-motion support
 *
 * Generated markup is not React server output. SPA-backed pages therefore
 * keep it in an independent static container until the client tree commits;
 * standalone pages can omit the SPA entrypoint entirely.
 */

import { readdirSync, existsSync } from "node:fs";
import { join, posix, resolve } from "node:path";
import {
    buildCsp,
    isMinimalDeploymentMode,
    normalizeBasePath,
    requireDeploymentOrigin,
    resolveAssetUrl,
} from "../src/lib/deployment";

/* ------------------------------------------------------------------ */
/*  Asset discovery                                                   */
/* ------------------------------------------------------------------ */

export interface DiscoveredAssets {
    jsEntry: string;           // Main index-XXXX.js
    cssEntry: string;          // Main index-XXXX.css
    preloads: string[];        // Modulepreload chunks (react, router, etc.)
    fontPreloads: string[];    // .woff2 preloads
}

const SITE_VARIANT = (process.env.VITE_SITE_VARIANT ?? process.env.SOYMUTDB_SITE_VARIANT ?? "external").trim().toLowerCase();
if (SITE_VARIANT !== "external" && SITE_VARIANT !== "internal") {
    throw new Error(`Invalid site variant "${SITE_VARIANT}". Use external or internal.`);
}
const DIST_DIR = resolve(process.cwd(), process.env.SOYMUTDB_DIST_DIR ?? "dist");
const ASSETS_DIR = join(DIST_DIR, "assets");

/**
 * Discover the hashed asset filenames produced by the Vite build.
 * Returns sensible defaults if assets haven't been built yet (so the
 * SSG script can still produce valid output in standalone mode).
 */
export function discoverAssets(): DiscoveredAssets {
    const defaults: DiscoveredAssets = {
        jsEntry: "assets/index.js",
        cssEntry: "assets/index.css",
        preloads: [],
        fontPreloads: [],
    };

    if (!existsSync(ASSETS_DIR)) return defaults;

    let jsEntry = defaults.jsEntry;
    let cssEntry = defaults.cssEntry;
    const preloads: string[] = [];
    const fontPreloads: string[] = [];

    try {
        const files = readdirSync(ASSETS_DIR);
        for (const f of files) {
            const p = posix.join("assets", f);
            if (f.startsWith("index-") && f.endsWith(".js")) {
                jsEntry = p;
            } else if (f.startsWith("index-") && f.endsWith(".css")) {
                cssEntry = p;
            } else if (f.endsWith(".js") && !f.endsWith(".js.map")) {
                // Code-split chunks we want to preload for critical routes.
                if (
                    /react-|router-|rolldown-runtime-|motion-vendor-/.test(f)
                ) {
                    preloads.push(p);
                }
            } else if (f.endsWith(".woff2") && /inter-latin-(400|500|600|700)|fraunces-latin-(400|500|600|700)|jetbrains-mono-latin-(400|500)/.test(f)) {
                fontPreloads.push(p);
            }
        }
    } catch {
        // Fall back to defaults
    }

    return { jsEntry, cssEntry, preloads, fontPreloads };
}

/* ------------------------------------------------------------------ */
/*  Template options                                                  */
/* ------------------------------------------------------------------ */

export interface BaseTemplateOptions {
    /** Page title (inside <title>). */
    title: string;
    /** Meta description. */
    description: string;
    /** <html lang="..."> value. Default "en". */
    lang?: string;
    /** ISO language code for <html lang>. */
    htmlClass?: string;
    /** Additional <head> markup (page-specific meta, JSON-LD, etc.). */
    headExtra?: string;
    /** Inlined build-time HTML, owned by an independent static container. */
    widgetsHtml?: string;
    /** Include the React SPA entrypoint. Disable for URLs with no SPA route. */
    spaEntrypoint?: boolean;
    /** Additional body-end scripts or markup. */
    bodyScripts?: string;
    /** Canonical URL (optional). */
    canonical?: string;
    /** JSON-LD structured data (optional). */
    jsonLd?: Record<string, unknown>;
    /** Search-engine directive, for example demo-only `noindex, nofollow`. */
    robots?: string;
    /** Base-aware path reported by the tracking pixel when canonical is omitted. */
    pagePath?: string;
    /** Pre-discovered assets (or we auto-discover). */
    assets?: DiscoveredAssets;
}

/* ------------------------------------------------------------------ */
/*  Theme init script                                                 */
/* ------------------------------------------------------------------ */

// Runs synchronously in <head> to prevent flash-of-unstyled-content (FOUC)
// when switching between light/dark themes.
const THEME_INIT_SCRIPT = `
(function() {
  try {
    var stored = localStorage.getItem('soymutdb-theme');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    var theme = stored || (prefersDark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.style.colorScheme = theme;
  } catch(e) {
    document.documentElement.setAttribute('data-theme', 'light');
  }
})();
`;


/* ------------------------------------------------------------------ */
/*  Cloudflare Web Analytics beacon (C3)                              */
/* ------------------------------------------------------------------ */

/**
 * Build-time Cloudflare Web Analytics token (VITE_CLOUDFLARE_ANALYTICS_TOKEN).
 *
 * The SSG build REWRITES dist/index.html after `vite build` (see
 * ssg-build.ts), so this template — not the Vite transformIndexHtml — is the
 * final authority for the shipped HTML. To keep behaviour identical in dev
 * and production, both places read the same variable and produce the same
 * markup: a static beacon <script> (no Workers involved) plus a widened CSP.
 *
 * NOTE: read from process.env (Cloudflare Pages injects dashboard
 * environment variables into the build environment; tsx does not load .env
 * files, which is fine — the variable is set in the Pages dashboard).
 */
const CF_ANALYTICS_TOKEN = (process.env.VITE_CLOUDFLARE_ANALYTICS_TOKEN ?? "").trim();

/** Full beacon <script> tag — empty string when no token is configured. */
const CF_BEACON_HTML = CF_ANALYTICS_TOKEN
    ? `<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon="${escapeHtmlAttribute(JSON.stringify({ token: CF_ANALYTICS_TOKEN }))}"></script>`
    : "";

/**
 * CSP content, widened with the beacon origins only when a token is
 * configured (keeps the no-token build byte-identical in behaviour).
 * Keep in sync with apps/web/public/_headers (browsers intersect both).
 */
const BASE_PATH = normalizeBasePath(process.env.VITE_BASE_URL ?? "/");
const MINIMAL_DEPLOYMENT = isMinimalDeploymentMode(process.env.VITE_DEPLOYMENT_MODE);
/**
 * Placeholder-origin documentation is intentionally stripped from the emitted
 * HTML. Keeping a `https://api.example.com` / `https://jbrowse.example.com`
 * note in the artifact would trip the strict production scan
 * (scripts/check-production-artifact.sh) and is documentation-only, so it
 * carries no runtime value. The instructions live in the SOURCE
 * (apps/web/index.html, base-template.ts, deploy/cloudflare.md).
 */
const CSP_DOC_COMMENT = "";
/**
 * The policy every page's `<meta>` tag is rendered with, and — until
 * `scripts/finalize-csp.ts` rewrites it with per-page hashes — the policy the
 * `_headers` file is expected to carry.
 *
 * Exported because the finalizer must start from the *same* string the template
 * used. Recomputing it there would duplicate the origin/deployment-mode
 * decisions below and reintroduce exactly the drift this single source exists to
 * prevent.
 */
export const CSP_CONTENT = buildCsp({
    apiOrigin: requireDeploymentOrigin(process.env.VITE_API_BASE_URL ?? process.env.SOYMUTDB_API_URL, "API"),
    jbrowseOrigin: MINIMAL_DEPLOYMENT
        ? undefined
        : requireDeploymentOrigin(
            process.env.VITE_JBROWSE_BASE_URL ?? process.env.VITE_JBROWSE_URL,
            "JBrowse",
        ),
}, Boolean(CF_ANALYTICS_TOKEN));

/* ------------------------------------------------------------------ */
/*  Tracking pixel (noscript-friendly analytics)                      */
/* ------------------------------------------------------------------ */

function renderTrackingPixel(pagePath: string): string {
    const pixelUrl = resolveAssetUrl(BASE_PATH, "track.gif");
    const encodedPath = encodeURIComponent(pagePath);
    return `
<!-- Tracking pixel: server-side analytics via 1x1 GIF. Works without JS. -->
<noscript>
  <img src="${escapeHtmlAttribute(`${pixelUrl}?ns=1&p=${encodedPath}`)}" alt="" width="1" height="1"
       style="position:absolute;width:1px;height:1px;overflow:hidden"
       referrerpolicy="no-referrer-when-downgrade" />
</noscript>
<img src="${escapeHtmlAttribute(`${pixelUrl}?p=${encodedPath}`)}" alt="" width="1" height="1"
     style="position:absolute;width:1px;height:1px;overflow:hidden"
     referrerpolicy="no-referrer-when-downgrade"
     loading="lazy" aria-hidden="true" />`;
}

/* ------------------------------------------------------------------ */
/*  Reduced-motion CSS                                                */
/* ------------------------------------------------------------------ */

const REDUCED_MOTION_STYLE = `
<style>
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
      scroll-behavior: auto !important;
    }
  }
</style>`;

/* ------------------------------------------------------------------ */
/*  Main render function                                              */
/* ------------------------------------------------------------------ */

export function renderBaseTemplate(opts: BaseTemplateOptions): string {
    const {
        title,
        description,
        lang = "en",
        headExtra = "",
        widgetsHtml = "",
        spaEntrypoint = true,
        bodyScripts = "",
        canonical,
        jsonLd,
        robots,
        pagePath: explicitPagePath,
    } = opts;

    const assets = opts.assets ?? discoverAssets();

    // Font preloads
    const fontPreloadHtml = assets.fontPreloads
        .map(
            (p) =>
                `<link rel="preload" href="${resolveAssetUrl(BASE_PATH, p)}" as="font" type="font/woff2" crossorigin />`,
        )
        .join("\n    ");

    // Module preloads
    const modulePreloadHtml = assets.preloads
        .map(
            (p) =>
                `<link rel="modulepreload" crossorigin href="${resolveAssetUrl(BASE_PATH, p)}" />`,
        )
        .join("\n    ");

    // Canonical URL
    const canonicalHtml = canonical
        ? `<link rel="canonical" href="${escapeHtmlAttribute(canonical)}" />`
        : "";

    // JSON-LD
    const jsonLdHtml = jsonLd
        ? `<script type="application/ld+json">${serializeJsonLd(jsonLd)}</script>`
        : "";

    const robotsHtml = robots
        ? `<meta name="robots" content="${escapeHtmlAttribute(robots)}" />`
        : "";

    // Open Graph
    const ogHtml = `
    <meta property="og:title" content="${escapeHtml(title)}" />
    <meta property="og:description" content="${escapeHtml(description)}" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="SoyMutDB" />
    <meta name="twitter:card" content="summary" />`;

    // Inject page path into tracking pixel
    const pagePath = explicitPagePath ?? (canonical ? new URL(canonical).pathname : "/");
    if (!pagePath.startsWith("/")) throw new Error("pagePath must be an absolute application path");
    const trackingHtml = renderTrackingPixel(pagePath);

    return `<!doctype html>
<html lang="${escapeHtmlAttribute(lang)}" data-theme="light" data-site-variant="${SITE_VARIANT}">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="${resolveAssetUrl(BASE_PATH, "favicon.svg")}" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="theme-color" content="#2F6F4F" />
    <meta name="description" content="${escapeHtml(description)}" />
    <meta name="author" content="SoyMutDB Consortium" />
    ${robotsHtml}
${ogHtml}
    ${canonicalHtml}

    ${CSP_DOC_COMMENT ? `<!-- ${CSP_DOC_COMMENT} -->` : ""}
    <meta
      http-equiv="Content-Security-Policy"
      content="${escapeHtmlAttribute(CSP_CONTENT)}"
    />

    <!-- Preconnect to font origins -->
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />

    <!-- Font preloads -->
    ${fontPreloadHtml}

    <!-- CSS -->
    <link rel="stylesheet" crossorigin href="${resolveAssetUrl(BASE_PATH, assets.cssEntry)}" />

    <!-- Reduced motion -->
    ${REDUCED_MOTION_STYLE}

    <!-- Theme initialisation (runs before paint to prevent FOUC) -->
    <script>${THEME_INIT_SCRIPT}</script>

    ${jsonLdHtml}
    ${CF_BEACON_HTML}
    ${headExtra}

    <title>${escapeHtml(title)}</title>
  </head>
  <body>
    <!-- ssg-content:start -->
    <div id="ssg-content" data-render-owner="static">${widgetsHtml}</div>
    <!-- ssg-content:end -->
    ${spaEntrypoint ? '<div id="root" hidden></div>' : ""}

    ${trackingHtml}

    ${spaEntrypoint ? `<!-- React SPA entrypoint: replaces #ssg-content only after its first commit -->
    <script type="module" crossorigin src="${resolveAssetUrl(BASE_PATH, assets.jsEntry)}"></script>
    ${modulePreloadHtml}` : ""}

    <!-- No inline widget loader: the build target is es2022, so every supported
         client has module support and src/lib/widget-loader.ts (DOMPurify-
         sanitised, booted from main.tsx) is the only loader that runs. The old
         snippet existed for non-module clients, duplicated the sanitizer, and
         wrote a widget-cache global on window that nothing ever read. The
         identifier is intentionally not repeated here so the contract test can
         assert its total absence from the document. -->
    ${bodyScripts}
  </body>
</html>`;
}

/**
 * Render a lightweight, base-aware compatibility redirect.
 * JavaScript preserves query/hash deep links; meta refresh is the no-JS fallback.
 */
export function renderRedirectTemplate(targetPath: string): string {
    const target = resolveAssetUrl(BASE_PATH, targetPath);
    const escapedTarget = escapeHtml(target);
    const scriptTarget = JSON.stringify(target);

    return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="robots" content="noindex" />
    <link rel="canonical" href="${escapedTarget}" />
    <meta http-equiv="refresh" content="0;url=${escapedTarget}" />
    <title>Redirecting — SoyMutDB</title>
    <script>window.location.replace(${scriptTarget} + window.location.search + window.location.hash);</script>
  </head>
  <body><p>Redirecting to <a href="${escapedTarget}">${escapedTarget}</a>…</p></body>
</html>`;
}

/* ------------------------------------------------------------------ */
/*  Utilities                                                         */
/* ------------------------------------------------------------------ */

function escapeHtml(s: string): string {
    return s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#x27;");
}

export function escapeHtmlAttribute(value: string): string {
    return escapeHtml(value).replace(/`/g, "&#x60;");
}

/**
 * Inverse of {@link escapeHtmlAttribute} for the entity forms `escapeHtml` emits.
 *
 * The CSP finalizer has to read a policy back out of an emitted document before
 * it can rewrite it, and it must reverse exactly the transformation this module
 * applied. Keeping the pair together is what makes that guarantee checkable:
 * `decodeHtmlAttribute(escapeHtmlAttribute(x)) === x` is asserted in
 * `scripts/__tests__/build-release-contracts.test.ts`.
 *
 * `&amp;` is decoded last, otherwise an input that literally contains `&amp;`
 * would be double-decoded.
 */
export function decodeHtmlAttribute(value: string): string {
    return value
        .replace(/&#x27;/g, "'")
        .replace(/&#x60;/g, "`")
        .replace(/&quot;/g, '"')
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&amp;/g, "&");
}

function serializeJsonLd(value: Record<string, unknown>): string {
    return JSON.stringify(value)
        .replace(/</g, "\\u003c")
        .replace(/>/g, "\\u003e")
        .replace(/&/g, "\\u0026")
        .replace(/\u2028/g, "\\u2028")
        .replace(/\u2029/g, "\\u2029");
}
