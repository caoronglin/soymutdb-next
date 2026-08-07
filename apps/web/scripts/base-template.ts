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
 * Pages built with this template hydrate the React SPA transparently
 * because the same JS/CSS bundles as the Vite build are included.
 */

import { readdirSync, existsSync } from "node:fs";
import { join, posix } from "node:path";

/* ------------------------------------------------------------------ */
/*  Asset discovery                                                   */
/* ------------------------------------------------------------------ */

export interface DiscoveredAssets {
    jsEntry: string;           // Main index-XXXX.js
    cssEntry: string;          // Main index-XXXX.css
    preloads: string[];        // Modulepreload chunks (react, router, etc.)
    fontPreloads: string[];    // .woff2 preloads
}

const DIST_DIR = join(process.cwd(), "dist");
const ASSETS_DIR = join(DIST_DIR, "assets");

/**
 * Discover the hashed asset filenames produced by the Vite build.
 * Returns sensible defaults if assets haven't been built yet (so the
 * SSG script can still produce valid output in standalone mode).
 */
export function discoverAssets(): DiscoveredAssets {
    const defaults: DiscoveredAssets = {
        jsEntry: "/assets/index.js",
        cssEntry: "/assets/index.css",
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
            const p = posix.join("/assets", f);
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
    /** Inlined widget HTML that will be placed inside #root for non-JS users. */
    widgetsHtml?: string;
    /** Additional body-end scripts or markup. */
    bodyScripts?: string;
    /** Canonical URL (optional). */
    canonical?: string;
    /** JSON-LD structured data (optional). */
    jsonLd?: Record<string, unknown>;
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
/*  Widget loader bootstrap (inline script)                           */
/* ------------------------------------------------------------------ */
const WIDGET_LOADER_SNIPPET = `
<!-- Widget loader: fetches dynamic widgets from /api/v1/widget/*.
     Inlined to avoid a blocking network request during hydration.
     Server HTML is double-sanitized (Jinja2 autoescape + bleach.clean);
     this snippet provides additional DOM-based sanitization before insertion. -->
<script>
(function() {
  'use strict';
  // Minimal widget fetcher — the full TypeScript module is imported by main.tsx
  // and will replace these placeholders once React hydrates. This minimal
  // version provides progressive enhancement for users without JS modules.

  // Trusted Types policy (CSP-compatible)
  var ttPolicy = (window.trustedTypes && trustedTypes.createPolicy)
    ? trustedTypes.createPolicy('soymutdb-widget', { createHTML: function(s) { return s; } })
    : null;

  // DOM-based sanitizer: parse through <template> (scripts don't execute)
  // and strip dangerous elements/attributes.
  function sanitizeHtml(html) {
    var tpl = document.createElement('template');
    tpl.innerHTML = html;  // template.content parses without executing scripts
    var doc = tpl.content;
    var forbidden = { SCRIPT:1, IFRA[truncated by convert_rollouts_to_sft: original new_string length=2985 chars for checker-safe SFT export]
}
  window.__soymutdb = window.__soymutdb || {};
  window.__soymutdb.widgetCache = window.__soymutdb.widgetCache || {};

  async function loadWidget(el) {
    var name = el.getAttribute('data-widget');
    if (!name || el.dataset.widgetLoaded === 'true') return;
    var params = el.getAttribute('data-widget-params');
    var cacheKey = name + (params ? '?' + params : '');
    var insert = function(node, html) {
      var safe = sanitizeHtml(html);
      if (ttPolicy) { node.innerHTML = ttPolicy.createHTML(safe); }
      else { node.innerHTML = safe; }
    };
    if (window.__soymutdb.widgetCache[cacheKey]) {
      insert(el, window.__soymutdb.widgetCache[cacheKey]);
      el.dataset.widgetLoaded = 'true';
      return;
    }
    try {
      var url = '/api/v1/widget/' + name + (params ? '?params=' + encodeURIComponent(params) : '');
      var res = await fetch(url, { headers: { 'Accept': 'text/html' } });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var html = await res.text();
      html = sanitizeHtml(html);
      window.__soymutdb.widgetCache[cacheKey] = html;
      insert(el, html);
      el.dataset.widgetLoaded = 'true';
      el.style.opacity = '1';
    } catch (err) {
      el.innerHTML = '<div class="widget-error" role="alert" style="padding:1rem;color:#c0392b;font-size:0.875rem">Widget failed to load.</div>';
    }
  }

  function scan(root) {
    root = root || document;
    var nodes = root.querySelectorAll('[data-widget]');
    Array.prototype.forEach.call(nodes, loadWidget);
  }

  window.__soymutdb.loadDynamicWidgets = scan;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { scan(); });
  } else {
    scan();
  }
})();
</script>`;

/* ------------------------------------------------------------------ */
/*  Tracking pixel (noscript-friendly analytics)                      */
/* ------------------------------------------------------------------ */

const TRACKING_PIXEL = `
<!-- Tracking pixel: server-side analytics via 1x1 GIF. Works without JS. -->
<noscript>
  <img src="/track.gif?ns=1&p={{PAGE_PATH}}" alt="" width="1" height="1"
       style="position:absolute;width:1px;height:1px;overflow:hidden"
       referrerpolicy="no-referrer-when-downgrade" />
</noscript>
<img src="/track.gif?p={{PAGE_PATH}}" alt="" width="1" height="1"
     style="position:absolute;width:1px;height:1px;overflow:hidden"
     referrerpolicy="no-referrer-when-downgrade"
     loading="lazy" aria-hidden="true" />`;

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
        bodyScripts = "",
        canonical,
        jsonLd,
    } = opts;

    const assets = opts.assets ?? discoverAssets();

    // Font preloads
    const fontPreloadHtml = assets.fontPreloads
        .map(
            (p) =>
                `<link rel="preload" href="${p}" as="font" type="font/woff2" crossorigin />`,
        )
        .join("\n    ");

    // Module preloads
    const modulePreloadHtml = assets.preloads
        .map(
            (p) =>
                `<link rel="modulepreload" crossorigin href="${p}" />`,
        )
        .join("\n    ");

    // Canonical URL
    const canonicalHtml = canonical
        ? `<link rel="canonical" href="${canonical}" />`
        : "";

    // JSON-LD
    const jsonLdHtml = jsonLd
        ? `<script type="application/ld+json">${JSON.stringify(jsonLd)}</script>`
        : "";

    // Open Graph
    const ogHtml = `
    <meta property="og:title" content="${escapeHtml(title)}" />
    <meta property="og:description" content="${escapeHtml(description)}" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="SoyMutDB" />
    <meta name="twitter:card" content="summary" />`;

    // Inject page path into tracking pixel
    const pagePath = canonical ? new URL(canonical).pathname : "/";
    const trackingHtml = TRACKING_PIXEL.replaceAll("{{PAGE_PATH}}", pagePath);

    return `<!doctype html>
<html lang="${lang}" data-theme="light">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="theme-color" content="#2F6F4F" />
    <meta name="description" content="${escapeHtml(description)}" />
    <meta name="author" content="SoyMutDB Consortium" />
${ogHtml}
    ${canonicalHtml}

    <!-- Content Security Policy -->
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob: https:; connect-src 'self' https:; base-uri 'self'; form-action 'self'; frame-ancestors 'self';"
    />

    <!-- Preconnect to font origins -->
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />

    <!-- Font preloads -->
    ${fontPreloadHtml}

    <!-- CSS -->
    <link rel="stylesheet" crossorigin href="${assets.cssEntry}" />

    <!-- Reduced motion -->
    ${REDUCED_MOTION_STYLE}

    <!-- Theme initialisation (runs before paint to prevent FOUC) -->
    <script>${THEME_INIT_SCRIPT}</script>

    ${jsonLdHtml}
    ${headExtra}

    <title>${escapeHtml(title)}</title>
  </head>
  <body>
    <div id="root">${widgetsHtml}</div>

    ${trackingHtml}

    <!-- React SPA entrypoint -->
    <script type="module" crossorigin src="${assets.jsEntry}"></script>
    ${modulePreloadHtml}

    ${WIDGET_LOADER_SNIPPET}
    ${bodyScripts}
  </body>
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
