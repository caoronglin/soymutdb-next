/**
 * Service Worker registration for the portal (OPT2-07).
 *
 * The build chain already emits `dist/sw.js` — `apps/web/scripts/gen-sw.js`
 * injects the precache manifest and the cache version into `public/sw.js` as the
 * last build step — but nothing ever registered it, so the offline / second-load
 * caching policy silently never activated. This module is that missing caller.
 *
 * Design constraints (see docs/design/service-worker.md §5):
 *
 * - **Production only.** Under `umi dev` the module graph is served unbundled
 *   and HMR rewrites module URLs; a cache-first SW would hand back stale modules
 *   and fight the dev server. `import.meta.env.PROD` is false there, so we no-op.
 * - **Base-aware.** The site is published under a subpath (e.g.
 *   `/soymutdb-next/`), so the script URL is resolved against
 *   `import.meta.env.BASE_URL` instead of a hardcoded `/sw.js`. The scope is left
 *   to the browser, which derives it from the script's own path — its parent
 *   directory. Hardcoding would register the wrong scope (or 404) on a subpath.
 * - **Progressive enhancement.** Registration is never awaited by the caller and
 *   every failure path (unsupported browser, non-http protocol, rejected
 *   `register()`) resolves quietly with at most a `console.warn`, so a broken SW
 *   cannot block the app mount.
 * - **Restrained updates.** We do not call `registration.update()` on every
 *   navigation; the browser's own byte-comparison of `sw.js` on navigation is
 *   enough, and forcing an update fetch on every route change would defeat the
 *   HTTP cache. A handle is returned for a future "update available" prompt.
 *
 * Nothing here knows about API vs. static caching: that policy lives entirely in
 * the worker (`public/sw.js`), which is where the offline behaviour is testable
 * as a unit.
 */

/** The slice of `navigator` this module needs (keeps tests free of DOM types). */
export interface ServiceWorkerNavigator {
  readonly serviceWorker?: {
    register(scriptURL: string): Promise<ServiceWorkerRegistration>;
  };
}

export interface RegisterServiceWorkerOptions {
  /**
   * Whether to register at all. Defaults to "production build and not disabled
   * via `VITE_SW_ENABLED=false`" — injectable because `import.meta.env.PROD`
   * cannot be rewritten inside a Vitest run.
   */
  enabled?: boolean;
  /** Deployment base (`import.meta.env.BASE_URL`); always has a trailing slash after normalization. */
  base?: string;
  /** Navigator-like object. Defaults to the global `navigator`. */
  nav?: ServiceWorkerNavigator;
  /** Location-like object, only used for the http(s) protocol guard. Defaults to the global `location`. */
  loc?: { protocol: string };
}

/**
 * Resolve the worker script relative to the deployment base.
 *
 * `import.meta.env.BASE_URL` is a root-relative path (`/` or `/soymutdb-next/`),
 * so `new URL("sw.js", base)` cannot be used directly — a root-relative string
 * is not a valid absolute base and throws. Joining is enough: the browser then
 * resolves the result against the document URL, keeping the subpath prefix.
 */
function resolveScriptUrl(base: string): string {
  const prefix = base.length === 0 || base.endsWith("/") ? base : `${base}/`;
  return `${prefix}sw.js`;
}

/** True when the build-time kill switch (`VITE_SW_ENABLED=false`) turns the worker off. */
function disabledByEnv(): boolean {
  // VITE_SW_ENABLED is not a built-in env key; normalize it explicitly.
  const flag = import.meta.env.VITE_SW_ENABLED as string | undefined;
  return flag?.trim().toLowerCase() === "false";
}

/**
 * Register the precache/offline service worker.
 *
 * @returns the registration handle when one was created, otherwise `undefined`.
 *          Never rejects.
 */
export async function registerServiceWorker(
  options: RegisterServiceWorkerOptions = {},
): Promise<ServiceWorkerRegistration | undefined> {
  const {
    enabled = import.meta.env.PROD && !disabledByEnv(),
    base = import.meta.env.BASE_URL,
    nav = typeof navigator === "undefined" ? undefined : navigator,
    loc = typeof location === "undefined" ? undefined : location,
  } = options;

  if (!enabled) return undefined;

  // Capability guard: Safari private mode / older embedded webviews expose
  // `navigator` without `serviceWorker`.
  const container = nav?.serviceWorker;
  if (!container) return undefined;

  // Only secure contexts are registrable. http is allowed so localhost AND the
  // container-network previews (http://<host>:4173) still work; file: and
  // chrome-extension: are not.
  const protocol = loc?.protocol;
  if (protocol && protocol !== "http:" && protocol !== "https:") return undefined;

  try {
    return await container.register(resolveScriptUrl(base));
  } catch (error) {
    // Best-effort: warn, never rethrow, so the React app can fire-and-forget.
    console.warn("[service-worker] registration failed", error);
    return undefined;
  }
}
