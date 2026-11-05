/**
 * First-party `pageview` producer for the public portal (B4).
 *
 * ## Contract
 *
 * The request carries **exactly two** parameters on `GET /track.gif`:
 * `event=pageview` and `page=<canonical template>`. The server-side allowlist
 * in `apps/api/app/services/analytics_privacy.py` is the authority; anything it
 * does not name collapses to `/other`.
 *
 * Deliberately **not** sent, matching the approved B1b ingress contract:
 *   - `site` — D5 was refused. A client-supplied variant is not an identity and
 *     the API stores no per-site column, so the parameter would be ignored at
 *     best and misleading at worst.
 *   - `q`, `widget` — free text accepted for compatibility and dropped.
 *   - `ref` / `source` — no self-supplied referrer.
 *
 * ## Cookies
 *
 * No cookie **value** is ever read, written or placed in the URL:
 * `document.cookie` is never touched. The image request is same-origin, so the
 * browser attaches its ordinary session cookie to it automatically — that is
 * normal transport, not a leak, and it is what lets the server count the
 * opaque `sm_sid` session. The privacy property is that no cookie material
 * reaches the URL or this module.
 *
 * ## What counts as a navigation
 *
 * A navigation is a change of **pathname**. The initial page and the
 * `onResolved` event that immediately follows it resolve to the same pathname
 * and therefore collapse into one beacon. Query-only and hash-only changes do
 * not move the pathname and are not navigations. Two different ids under one
 * template (`/mutants/a` -> `/mutants/b`) are two navigations and both send,
 * even though they map to the same canonical template.
 *
 * ## Consumers
 *
 * There is exactly **one** consumer today: `react-app.tsx` initialises this
 * module once per mounted router and disposes it once on unmount. That single-
 * consumer fact is load-bearing for the lifecycle below, so it is recorded
 * here rather than defended with reference counting: the `WeakMap` state and
 * the `disposed` flag already make a repeated `init` and a double `dispose`
 * safe, which is all a StrictMode remount needs. A second concurrent consumer
 * would require a real refcount, so add one at that point — do not pre-build it.
 */

/** Fallback template for anything the server allowlist does not name. */
export const OTHER_PAGE_TEMPLATE = "/other";

/**
 * Finite, explicit `leaf.fullPath` -> canonical template map.
 *
 * Keys are the router's **fullPath**, not its `routeId`. They are not
 * interchangeable: the six `/search/*` children are registered as children of
 * the `/search` route, so their real `routeId` is `/search/search/genes` and a
 * `routeId`-keyed allowlist never matched them — `/search/genes` silently
 * walked out to `/search` and reported the wrong page. `fullPath` is the
 * canonical, human-readable form (`/search/genes`) and is stable.
 *
 * This is a closed allowlist, not a `$` -> `:` rewrite: a `fullPath` absent
 * here yields `/other`. Note `/mutants/$id` -> `/mutants/:publicId`; the
 * router's parameter name deliberately differs from the server's fixed one,
 * so a mechanical substitution would silently degrade to `/other`.
 */
const FULL_PATH_TO_TEMPLATE: Readonly<Record<string, string>> = Object.freeze({
  "/": "/",
  "/about": "/about",
  "/analytics": "/analytics",
  // The `/analyses` and `/tools` routes are registered with a slash-less
  // `path`, so their `fullPath` is slash-less even though their id is not.
  "/analyses": "/analyses",
  "/analyses/$jobId": "/analyses/:jobId",
  "/analyses/fastp": "/analyses/fastp",
  "/analyses/scanpy": "/analyses/scanpy",
  "/blast": "/blast",
  "/browser": "/browser",
  "/compare": "/compare",
  "/downloads": "/downloads",
  "/genes/": "/genes",
  "/genes/$geneId": "/genes/:geneId",
  "/guide": "/guide",
  "/help": "/help",
  "/login": "/login",
  "/mutants/": "/mutants",
  "/mutants/$id": "/mutants/:publicId",
  "/news/": "/news",
  "/news/$slug": "/news/:slug",
  "/publications": "/publications",
  "/search": "/search",
  "/search/blast": "/search/blast",
  "/search/gbrowse": "/search/gbrowse",
  "/search/genes": "/search/genes",
  "/search/location": "/search/location",
  "/search/primer": "/search/primer",
  "/search/tools": "/search/tools",
  "/seed-request": "/seed-request",
  "/sra": "/sra",
  "/tools": "/tools",
  "/tools/enrichment": "/tools/enrichment",
  "/tools/exppattern": "/tools/exppattern",
  "/tools/seqfetch": "/tools/seqfetch",
  "/tools/sequence": "/tools/sequence",
  "/variants/": "/variants",
  // `/genome-view` exists in the router but is NOT in the server allowlist,
  // so it intentionally resolves to `/other` below.
});

/** Minimal router surface this module needs, so tests can supply a stub. */
export interface PageviewRouter {
  matchRoutes(
    pathname: string,
  ): ReadonlyArray<{ fullPath?: string; pathname?: string; routeId?: string }>;
  readonly state: { location: { pathname: string } };
  subscribe(
    eventType: "onResolved",
    handler: (event: unknown) => void,
  ): () => void;
}

export interface PageviewOptions {
  /** Resolved `/track.gif` URL. */
  endpoint: string;
  /** Injection seam for tests; defaults to a real `Image` pixel. */
  send?: (url: string) => void;
  /** Injection seam for tests; defaults to live DNT detection. */
  isDntEnabled?: () => boolean;
}

interface RouterState {
  /** Survives dispose so a StrictMode remount does not re-send the first page. */
  initialised: boolean;
  lastPathname: string | null;
  unsubscribe: (() => void) | null;
  disposed: boolean;
}

/**
 * Per-router bookkeeping. A `WeakMap` keeps state tied to the router's
 * lifetime, so a second `init` on the same router neither re-subscribes nor
 * re-sends the first page, while a router that is garbage collected takes its
 * state with it.
 */
const routerStates = new WeakMap<PageviewRouter, RouterState>();

function readState(router: PageviewRouter): RouterState {
  let state = routerStates.get(router);
  if (!state) {
    state = {
      initialised: false,
      lastPathname: null,
      unsubscribe: null,
      disposed: false,
    };
    routerStates.set(router, state);
  }
  return state;
}

/**
 * DNT is re-read before every send rather than once at init, so a user who
 * enables it mid-session stops the producer immediately.
 */
export function isDoNotTrackEnabled(): boolean {
  if (typeof navigator !== "undefined" && navigator.doNotTrack === "1") {
    return true;
  }
  if (typeof window !== "undefined") {
    const legacy = (window as Window & { msDoNotTrack?: string }).msDoNotTrack;
    if (legacy === "1") return true;
  }
  return false;
}

function defaultSend(url: string): void {
  if (typeof Image === "undefined") return;
  // Assigning `src` performs the request. The browser attaches same-origin
  // cookies to it on its own; no cookie value is read or appended here.
  const img = new Image();
  // `no-referrer` must be set **before** `src`, because assigning `src` is
  // what starts the request. Without it the browser attaches a `Referer`
  // header to the beacon, which would hand the server the previous page's URL.
  img.referrerPolicy = "no-referrer";
  img.src = url;
}

/** Drop trailing slashes so `/genes/` and `/genes` compare equal. */
function normalisePath(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  return trimmed === "" ? "/" : trimmed;
}

/**
 * Map a pathname to the canonical template the server allowlist recognises.
 *
 * Exported for the regression test that pins the allowlist itself; the router
 * dependency is optional so a bare pathname can be asserted directly.
 */
export function toPageTemplate(
  pathname: string,
  router?: Pick<PageviewRouter, "matchRoutes">,
): string {
  if (router) {
    const matches = router.matchRoutes(pathname);
    const leaf = matches[matches.length - 1];
    if (leaf) {
      // The leaf's matched `pathname` must account for the *whole* input. If it
      // does not, the router only partially matched (for example
      // `/mutants/a/b/c` yields `pathname: /mutants/a`), and reporting
      // `/mutants/:publicId` for it would claim a page the user never reached.
      if (
        typeof leaf.pathname === "string" &&
        normalisePath(leaf.pathname) === normalisePath(pathname)
      ) {
        const mapped =
          typeof leaf.fullPath === "string"
            ? FULL_PATH_TO_TEMPLATE[leaf.fullPath]
            : undefined;
        // A `fullPath` the server allowlist does not name (for example
        // `/genome-view`) stays `/other` rather than walking outwards: a parent
        // match is not evidence the parent page was requested.
        if (mapped !== undefined) return mapped;
      }
    }
    return OTHER_PAGE_TEMPLATE;
  }

  // Map keys are TanStack route fullPaths, some of which carry a trailing slash.
  // Try the caller's spelling, then the normalised variants, so both
  // "/genes" and "/genes/" resolve.
  const trimmed = pathname.replace(/\/+$/, "");
  for (const candidate of [pathname, trimmed, trimmed + "/"]) {
    const mapped = FULL_PATH_TO_TEMPLATE[candidate];
    if (mapped !== undefined) return mapped;
  }
  return OTHER_PAGE_TEMPLATE;
}

/**
 * Start emitting `pageview`s for `router`. Returns a dispose function that
 * unsubscribes; calling it more than once is safe, and a later `init` on the
 * same router resumes cleanly without duplicating the first beacon.
 */
export function initPageviewTracking(
  router: PageviewRouter,
  options: PageviewOptions,
): () => void {
  const state = readState(router);
  // Guard on the live subscription only. A previous dispose() clears it, which
  // is what lets a StrictMode remount resume; while a subscription is live a
  // repeated init is a no-op and neither re-subscribes nor re-sends page one.
  if (state.unsubscribe) return () => {};

  const send = options.send ?? defaultSend;
  const isDntEnabled = options.isDntEnabled ?? isDoNotTrackEnabled;
  state.disposed = false;

  const emit = (pathname: string): void => {
    if (state.disposed) return;
    if (isDntEnabled()) return;
    const params = new URLSearchParams();
    params.set("event", "pageview");
    params.set("page", toPageTemplate(pathname, router));
    send(options.endpoint + "?" + params.toString());
  };

  if (!state.initialised) {
    state.initialised = true;
    state.lastPathname = router.state.location.pathname;
    emit(state.lastPathname);
  }

  state.unsubscribe = router.subscribe("onResolved", () => {
    const pathname = router.state.location.pathname;
    // Pathname equality is the whole navigation test: it absorbs the initial
    // page's trailing `onResolved`, ignores query/hash-only edits, and still
    // counts `/mutants/a` -> `/mutants/b` because the pathnames differ.
    if (pathname === state.lastPathname) return;
    state.lastPathname = pathname;
    emit(pathname);
  });

  return () => {
    if (state.disposed) return;
    state.disposed = true;
    try {
      state.unsubscribe?.();
    } catch {
      /* a router torn down first must not break unmount */
    }
    state.unsubscribe = null;
  };
}
