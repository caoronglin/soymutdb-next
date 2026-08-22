/**
 * Widget Loader
 *
 * Fetches server-rendered HTML widgets from /api/v1/widget/{name}, sanitises
 * them with DOMPurify, caches them in memory, and inserts them into the DOM
 * with a bounded fade-in (respecting prefers-reduced-motion).
 *
 * Supports Trusted Types via createTrustedHtmlPolicy() for strict CSP
 * environments that disallow direct innerHTML assignment.
 */
import DOMPurify from "dompurify";
import { resolveAssetUrl } from "./deployment";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface WidgetFetchOptions {
    /** Additional query params to send to the widget endpoint. */
    params?: Record<string, unknown>;
    /** Bypass the in-memory cache and refetch. */
    force?: boolean;
    /** Abort signal for cancelling in-flight requests. */
    signal?: AbortSignal;
}

interface CachedEntry {
    html: string;
    fetchedAt: number;
}

/* ------------------------------------------------------------------ */
/*  In-memory cache                                                   */
/* ------------------------------------------------------------------ */

const widgetCache = new Map<string, CachedEntry>();

function cacheKey(name: string, params?: Record<string, unknown>): string {
    return params ? `${name}?${JSON.stringify(params)}` : name;
}

/* ------------------------------------------------------------------ */
/*  Trusted Types support                                             */
/* ------------------------------------------------------------------ */

let trustedPolicy: { createHTML: (input: string) => string } | null = null;

/**
 * Creates (once) a TrustedHTML policy for widget content so we can assign
 * to innerHTML under a strict `require-trusted-types-for` CSP directive.
 *
 * The returned policy name is `soymutdb-widget`.  Because the HTML has
 * already been sanitised by DOMPurify, this policy is a pass-through.
 */
export function createTrustedHtmlPolicy():
    | { createHTML: (input: string) => string }
    | null {
    if (trustedPolicy) return trustedPolicy;
    if (typeof window === "undefined") return null;
    if (!("trustedTypes" in window)) return null;

    const tt = (window as unknown as {
        trustedTypes?: {
            createPolicy: (
                name: string,
                rules: { createHTML: (s: string) => string },
            ) => { createHTML: (s: string) => string };
        };
    }).trustedTypes;

    if (!tt) return null;

    try {
        trustedPolicy = tt.createPolicy("soymutdb-widget", {
            createHTML: (s: string) => s, // DOMPurify already cleaned it
        });
    } catch {
        // Policy already exists or creation blocked — fall back to raw strings.
        trustedPolicy = null;
    }
    return trustedPolicy;
}

/* ------------------------------------------------------------------ */
/*  Fetching + sanitisation                                           */
/* ------------------------------------------------------------------ */

/**
 * Fetch a server-rendered widget by name.
 *
 * @param name    Widget identifier (path segment under /api/v1/widget/).
 * @param options Fetch options (params, cache bypass, abort signal).
 * @returns Sanitised HTML string safe for innerHTML assignment.
 */
export async function fetchWidget(
    name: string,
    options: WidgetFetchOptions = {},
): Promise<string> {
    const { params, force = false, signal } = options;
    const key = cacheKey(name, params);

    if (!force) {
        const cached = widgetCache.get(key);
        if (cached) return cached.html;
    }

    const url = new URL(resolveAssetUrl(import.meta.env.BASE_URL, `api/v1/widget/${name}`), window.location.origin);
    if (params) {
        url.searchParams.set("params", JSON.stringify(params));
    }

    const res = await fetch(url.toString(), {
        headers: { Accept: "text/html" },
        signal,
    });

    if (!res.ok) {
        throw new Error(
            `Widget "${name}" fetch failed: ${res.status} ${res.statusText}`,
        );
    }

    const raw = await res.text();
    const sanitised = DOMPurify.sanitize(raw, {
        USE_PROFILES: { html: true },
        ADD_ATTR: ["data-widget", "data-widget-name", "data-widget-params"],
        FORBID_TAGS: ["script", "style", "iframe", "form"],
        FORBID_ATTR: ["onerror", "onload", "onclick", "onmouseover"],
    });

    widgetCache.set(key, { html: sanitised, fetchedAt: Date.now() });
    return sanitised;
}

/** Manually evict a widget from the cache (e.g. after a mutation). */
export function invalidateWidget(
    name: string,
    params?: Record<string, unknown>,
): void {
    widgetCache.delete(cacheKey(name, params));
}

/** Wipe the entire widget cache. */
export function clearWidgetCache(): void {
    widgetCache.clear();
}

/* ------------------------------------------------------------------ */
/*  DOM insertion                                                     */
/* ------------------------------------------------------------------ */

/**
 * Insert sanitised widget HTML with a bounded fade-in that honours
 * `prefers-reduced-motion`.
 */
export function insertWidget(container: HTMLElement, html: string): void {
    // Ensure Trusted Types policy exists (no-op if unsupported).
    const policy = createTrustedHtmlPolicy();

    // Initial hidden state for animation (skip if reduced-motion).
    const prefersReduced =
        typeof window !== "undefined" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (!prefersReduced) {
        container.style.opacity = "0";
        container.style.transform = "translateY(8px)";
    }

    // Assign sanitised HTML, wrapping in TrustedHTML if policy available.
    if (policy) {
        container.innerHTML = policy.createHTML(html) as unknown as string;
    } else {
        container.innerHTML = html;
    }

    if (!prefersReduced) {
        requestAnimationFrame(() => {
            container.style.transition = "opacity 160ms ease-out, transform 160ms ease-out";
            container.style.opacity = "1";
            container.style.transform = "translateY(0)";
        });
    }
}

/* ------------------------------------------------------------------ */
/*  Auto-discovery                                                    */
/* ------------------------------------------------------------------ */

/**
 * Scan the document for elements with `[data-widget]` attributes and
 * fetch + insert each one.  Called once on app mount; safe to call
 * again after navigation (idempotent — already-loaded widgets are
 * served from the in-memory cache).
 *
 * Expected markup:
 * ```html
 * <div data-widget="variant_table"
 *      data-widget-params='{"gene":"Glyma.01G123400","limit":20}'></div>
 * ```
 */
export async function loadDynamicWidgets(root: ParentNode = document): Promise<void> {
    const nodes = root.querySelectorAll<HTMLElement>("[data-widget]");

    const tasks = Array.from(nodes).map(async (el) => {
        // Skip widgets that already received content (marked by us).
        if (el.dataset.widgetLoaded === "true") return;

        const name = el.dataset.widget;
        if (!name) return;

        let params: Record<string, unknown> | undefined;
        const rawParams = el.dataset.widgetParams;
        if (rawParams) {
            try {
                params = JSON.parse(rawParams);
            } catch {
                console.warn(
                    `[widget-loader] Invalid JSON in data-widget-params for "${name}"`,
                );
            }
        }

        try {
            const html = await fetchWidget(name, { params });
            insertWidget(el, html);
            el.dataset.widgetLoaded = "true";
        } catch (err) {
            console.error(`[widget-loader] Failed to load widget "${name}":`, err);
            el.innerHTML =
                '<div class="widget-error" role="alert">Widget failed to load.</div>';
        }
    });

    await Promise.allSettled(tasks);
}

/* ------------------------------------------------------------------ */
/*  Initialisation                                                    */
/* ------------------------------------------------------------------ */

let initialised = false;

/**
 * Boot the widget system: sets up the Trusted Types policy, seeds
 * DOMPurify hooks if needed, and performs the first scan for dynamic
 * placeholders on the page.
 */
export function initWidgetLoader(): void {
    if (initialised) return;
    initialised = true;

    createTrustedHtmlPolicy();

    // Hook DOMPurify to remove any remaining event-handler attributes
    // that might sneak through custom configs.
    if (typeof DOMPurify.addHook === "function") {
        DOMPurify.addHook("afterSanitizeAttributes", (node: Element) => {
            if (node instanceof Element) {
                for (const attr of Array.from(node.attributes)) {
                    if (attr.name.startsWith("on")) {
                        node.removeAttribute(attr.name);
                    }
                }
            }
        });
    }

    // First load — run after DOM is ready.
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => loadDynamicWidgets(), {
            once: true,
        });
    } else {
        void loadDynamicWidgets();
    }
}
