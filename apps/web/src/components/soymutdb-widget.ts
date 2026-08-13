/**
 * <soymutdb-widget> — Custom Element for lazy-loaded, isolated widgets.
 *
 * Features:
 *   - Shadow DOM for full style isolation (with a minimal reset).
 *   - IntersectionObserver-based lazy loading (rootMargin 200px).
 *   - DOMPurify sanitisation before insertion (with fallback sanitizer).
 *   - Loading skeleton + error state UI with retry button.
 *   - Dispatches `widget:loaded` / `widget:error` events on the host.
 *   - Respects Save-Data and prefers-reduced-motion.
 *   - Container queries in shadow CSS for responsive widgets.
 *   - Uses requestIdleCallback for non-critical post-load work.
 *   - PerformanceObserver logs widget load time marks.
 *
 * Usage (HTML, no React required):
 *   <soymutdb-widget name="gene-card" params='{"geneId":"Glyma.01G123400"}'></soymutdb-widget>
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

// ---------------------------------------------------------------------------
// DOMPurify is loaded dynamically so the custom element can be used even if
// dompurify is not bundled (we fall back to a minimal sanitizer).
// ---------------------------------------------------------------------------
type Purify = { sanitize: (html: string, opts?: unknown) => string };
let DOMPurifyInstance: Purify | null = null;

async function loadDOMPurify(): Promise<Purify | null> {
    if (DOMPurifyInstance) return DOMPurifyInstance;
    try {
        // Dynamic import — works at runtime since dompurify is a dependency;
        // using eval-free indirection to avoid static module resolution issues.
        const specifier = 'dompurify';
        const mod = (await import(/* @vite-ignore */ specifier)) as any;
        DOMPurifyInstance = mod.default ?? mod;
        return DOMPurifyInstance;
    } catch {
        return null;
    }
}

/** Minimal fallback sanitizer — removes <script>, event handlers, <iframe>, etc. */
function fallbackSanitize(html: string): string {
    const tpl = document.createElement('template');
    tpl.innerHTML = html;
    const doc = tpl.content as any;
    const forbidden = new Set(['script', 'iframe', 'form', 'object', 'embed']);
    const walker = doc.createTreeWalker(doc, NodeFilter.SHOW_ELEMENT) as TreeWalker;
    const toRemove: Element[] = [];
    let node = walker.nextNode() as Element | null;
    while (node) {
        if (forbidden.has(node.tagName.toLowerCase())) {
            toRemove.push(node);
        } else {
            for (const attr of Array.from(node.attributes)) {
                if (attr.name.startsWith('on')) {
                    node.removeAttribute(attr.name);
                }
            }
        }
        node = walker.nextNode() as Element | null;
    }
    for (const el of toRemove) el.remove();
    return tpl.innerHTML;
}

async function sanitize(html: string): Promise<string> {
    const purify = await loadDOMPurify();
    if (purify && typeof purify.sanitize === 'function') {
        return purify.sanitize(html, {
            USE_PROFILES: { html: true },
            ADD_ATTR: ['data-widget', 'data-widget-name', 'data-widget-params'],
            FORBID_TAGS: ['script', 'iframe', 'form'],
            FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover'],
        }) as string;
    }
    return fallbackSanitize(html);
}

// ---------------------------------------------------------------------------
// Shadow DOM stylesheet (includes container queries + :has() usage).
// ---------------------------------------------------------------------------
const SHADOW_CSS = /* css */ `
  :host {
    display: block;
    container-type: inline-size;
    container-name: widget;
    position: relative;
  }

  /* Minimal reset inside shadow root */
  *, *::before, *::after { box-sizing: border-box; }

  .widget-shell {
    min-height: 80px;
    border-radius: 12px;
    font-family: var(--font-sans, Inter, ui-sans-serif, system-ui, sans-serif);
    color: inherit;
  }

  /* Skeleton */
  .skeleton {
    display: grid;
    gap: 0.625rem;
    padding: 1rem;
  }
  .skeleton-bar {
    height: 14px;
    border-radius: 6px;
    background: color-mix(in oklch, currentColor 10%, transparent);
    animation: skel 1.5s ease-in-out infinite;
  }
  .skeleton-bar:nth-child(1) { width: 60%; }
  .skeleton-bar:nth-child(2) { width: 90%; }
  .skeleton-bar:nth-child(3) { width: 75%; }
  .skeleton-bar:nth-child(4) { width: 40%; height: 20px; border-radius: 8px; margin-top: 8px; }

  @keyframes skel {
    0%, 100% { opacity: 1; }
    50%      { opacity: 0.4; }
  }

  /* Error state */
  .error {
    padding: 1rem;
    border: 1px dashed color-mix(in oklch, oklch(0.55 0.2 27) 50%, transparent);
    border-radius: 12px;
    color: oklch(0.55 0.18 27);
    background: color-mix(in oklch, oklch(0.55 0.2 27) 6%, transparent);
    font-size: 0.875rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
  }
  .error button {
    margin-left: auto;
    background: transparent;
    border: 1px solid currentColor;
    border-radius: 6px;
    padding: 2px 10px;
    font-size: 0.75rem;
    cursor: pointer;
    color: inherit;
  }

  /* Content area */
  .content {
    animation: wdgt-fade 300ms ease-out both;
  }
  @keyframes wdgt-fade {
    from { opacity: 0; transform: translateY(4px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  /* Container queries — responsive layout without viewport queries */
  @container widget (max-width: 400px) {
    .widget-shell { font-size: 0.875rem; }
    .skeleton { padding: 0.75rem; gap: 0.5rem; }
  }
  @container widget (min-width: 700px) {
    .skeleton { grid-template-columns: 1fr 1fr; }
    .skeleton-bar:nth-child(1),
    .skeleton-bar:nth-child(3) { grid-column: 1; }
    .skeleton-bar:nth-child(2),
    .skeleton-bar:nth-child(4) { grid-column: 2; }
  }

  /* :has() parent selector — style shell differently when content shows an error */
  .widget-shell:has(.error) {
    box-shadow: 0 0 0 1px color-mix(in oklch, oklch(0.55 0.2 27) 20%, transparent) inset;
  }

  /* Save-Data / reduced motion: kill all animations */
  @media (prefers-reduced-motion: reduce) {
    .content, .skeleton-bar { animation: none !important; }
  }
  :host([data-save-data="true"]) .content { animation: none !important; }
`;

// ---------------------------------------------------------------------------
// Custom Element
// ---------------------------------------------------------------------------

const STATE = {
    IDLE: 'idle',
    LOADING: 'loading',
    LOADED: 'loaded',
    ERROR: 'error',
} as const;

type WidgetState = (typeof STATE)[keyof typeof STATE];

// Trusted Types policy cached at module level to avoid duplicate-create errors
let wcTrustedPolicy: { createHTML: (s: string) => string } | null | undefined = undefined;

function getWcTrustedPolicy(): { createHTML: (s: string) => string } | null {
    if (wcTrustedPolicy !== undefined) return wcTrustedPolicy;
    const tt = (window as any).trustedTypes;
    if (!tt?.createPolicy) {
        wcTrustedPolicy = null;
        return null;
    }
    try {
        const policy: { createHTML: (s: string) => string } = tt.createPolicy('soymutdb-wc', { createHTML: (s: string) => s });
        wcTrustedPolicy = policy;
    } catch {
        // Policy already created — fall back to null (raw HTML assignment)
        wcTrustedPolicy = null;
    }
    return wcTrustedPolicy ?? null;
}

class SoyMutDBWidget extends HTMLElement {
    private shadow!: ShadowRoot;
    private observer: IntersectionObserver | null = null;
    private controller: AbortController | null = null;
    private _state: WidgetState = STATE.IDLE;

    static get observedAttributes() {
        return ['name', 'params'];
    }

    connectedCallback() {
        if (!this.shadowRoot) {
            this.shadow = this.attachShadow({ mode: 'open' });
            const style = document.createElement('style');
            style.textContent = SHADOW_CSS;
            this.shadow.appendChild(style);
        }
        // Detect Save-Data
        const conn = (navigator as any).connection;
        if (conn?.saveData) {
            this.dataset.saveData = 'true';
        }
        this.setupLazyLoad();
    }

    disconnectedCallback() {
        this.observer?.disconnect();
        this.controller?.abort();
    }

    attributeChangedCallback(name: string, oldVal: string | null, newVal: string | null) {
        if (oldVal === newVal) return;
        if (name === 'name' || name === 'params') {
            if (this._state !== STATE.IDLE) {
                this._state = STATE.IDLE;
                this.controller?.abort();
                this.setupLazyLoad();
            }
        }
    }

    // ---- Lazy loading via IntersectionObserver --------------------------------

    private setupLazyLoad() {
        this.observer?.disconnect();
        this.renderSkeleton();

        if (typeof IntersectionObserver === 'undefined') {
            this.load();
            return;
        }

        this.observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (entry.isIntersecting) {
                        this.observer?.disconnect();
                        this.observer = null;
                        this.load();
                        break;
                    }
                }
            },
            { rootMargin: '200px', threshold: 0 },
        );
        this.observer.observe(this);
    }

    // ---- Fetch + render -------------------------------------------------------

    async load() {
        const name = this.getAttribute('name');
        if (!name) {
            this.renderError('Missing "name" attribute');
            return;
        }
        this._state = STATE.LOADING;
        this.renderSkeleton();
        this.controller = new AbortController();

        const t0 = performance.now();
        this.recordMark(name, 'fetch-start');

        try {
            let params: Record<string, unknown> | undefined;
            const rawParams = this.getAttribute('params');
            if (rawParams) {
                try { params = JSON.parse(rawParams); } catch { /* ignore */ }
            }

            const url = new URL(`${import.meta.env.BASE_URL}api/v1/widget/${name}`, window.location.origin);
            if (params) url.searchParams.set('params', JSON.stringify(params));

            const res = await fetch(url.toString(), {
                headers: { Accept: 'text/html' },
                signal: this.controller.signal,
            });

            if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
            const html = await res.text();
            const clean = await sanitize(html);
            this.renderContent(clean);
            this._state = STATE.LOADED;
            this.recordMark(name, 'fetch-end');
            this.dispatch('widget:loaded', { name, elapsedMs: performance.now() - t0 });

            this.scheduleIdleInit(name);
        } catch (err) {
            if ((err as Error).name === 'AbortError') return;
            const msg = err instanceof Error ? err.message : String(err);
            this.renderError(msg);
            this._state = STATE.ERROR;
            this.dispatch('widget:error', { name, error: msg });
        }
    }

    // ---- Render helpers -------------------------------------------------------

    private renderSkeleton() {
        this.shadow.querySelector('.widget-shell')?.remove();
        const shell = document.createElement('div');
        shell.className = 'widget-shell';
        shell.innerHTML =
            '<div class="skeleton" role="status" aria-live="polite" aria-label="Loading widget">' +
            '<div class="skeleton-bar"></div>' +
            '<div class="skeleton-bar"></div>' +
            '<div class="skeleton-bar"></div>' +
            '<div class="skeleton-bar"></div>' +
            '</div>';
        this.shadow.appendChild(shell);
    }

    private renderError(message: string) {
        this.shadow.querySelector('.widget-shell')?.remove();
        const shell = document.createElement('div');
        shell.className = 'widget-shell';
        const safeMsg = message.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!));
        shell.innerHTML =
            '<div class="error" role="alert">' +
            `<span>⚠ Widget failed to load${safeMsg ? `: ${safeMsg}` : ''}</span>` +
            '<button type="button" class="retry">Retry</button>' +
            '</div>';
        shell.querySelector('.retry')?.addEventListener('click', () => this.load());
        this.shadow.appendChild(shell);
    }

    private renderContent(html: string) {
        this.shadow.querySelector('.widget-shell')?.remove();
        const shell = document.createElement('div');
        shell.className = 'widget-shell';
        const content = document.createElement('div');
        content.className = 'content';
        // Trusted Types aware innerHTML — cached policy avoids re-creation errors
        const policy = getWcTrustedPolicy();
        content.innerHTML = policy ? policy.createHTML(html) : html;
        shell.appendChild(content);
        this.shadow.appendChild(shell);
    }

    // ---- Event dispatch -------------------------------------------------------

    private dispatch(type: string, detail: unknown) {
        this.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
    }

    // ---- Performance marks + idle init ---------------------------------------

    private recordMark(name: string, label: string) {
        if (typeof performance !== 'undefined' && performance.mark) {
            try { performance.mark(`widget:${name}:${label}`); } catch { /* ignore */ }
        }
    }

    private scheduleIdleInit(name: string) {
        const ric: (cb: () => void) => number =
            (window as any).requestIdleCallback || ((cb: () => void) => window.setTimeout(cb, 200) as unknown as number);
        ric(() => {
            // Dev-only performance logging via PerformanceObserver.
            const isDev = (import.meta as any).env?.DEV === true;
            if (isDev && typeof PerformanceObserver !== 'undefined') {
                try {
                    const observer = new PerformanceObserver((list) => {
                        for (const entry of list.getEntries()) {
                            if (typeof entry.name === 'string' && entry.name.startsWith(`widget:${name}:`)) {
                                console.debug(`[widget-perf] ${entry.name}`, entry.startTime.toFixed(1));
                            }
                        }
                    });
                    observer.observe({ entryTypes: ['mark'] });
                    setTimeout(() => observer.disconnect(), 5000);
                } catch { /* entry type 'mark' may not be supported */ }
            }
        });
    }

    // Public imperative API
    refresh() {
        this._state = STATE.IDLE;
        this.load();
    }
}

// Register once (browsers deduplicate).
if (typeof customElements !== 'undefined' && !customElements.get('soymutdb-widget')) {
    customElements.define('soymutdb-widget', SoyMutDBWidget);
}

export { SoyMutDBWidget };
