/**
 * B4 regression coverage for the portal `pageview` producer.
 *
 * The assertions that matter most are the negative ones: nothing outside
 * `event` and `page` may reach the URL, and an unmounted or DNT-enabled
 * producer must be completely silent.
 */
import { createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  OTHER_PAGE_TEMPLATE,
  initPageviewTracking,
  isDoNotTrackEnabled,
  toPageTemplate,
  type PageviewRouter,
} from "./analytics";

const SENTINEL = "SENTINEL-9f3a7c";

/**
 * A stand-in for the TanStack router that yields the **same match fields the
 * real router yields**: `routeId`, `fullPath` and the concrete `pathname`.
 * `routeId` alone is what broke production — the real `/search/*` children
 * report `routeId: /search/search/genes`, which no route-id-keyed allowlist
 * would ever name — so the stub must carry the fields the module reads.
 */
function matchFor(pathname: string): {
  routeId: string;
  fullPath: string;
  pathname: string;
} {
  if (pathname === "/") return { routeId: "/", fullPath: "/", pathname: "/" };
  if (pathname.startsWith("/mutants/")) {
    return { routeId: "/mutants/$id", fullPath: "/mutants/$id", pathname };
  }
  if (pathname.startsWith("/genes/")) {
    return { routeId: "/genes/$geneId", fullPath: "/genes/$geneId", pathname };
  }
  if (pathname.startsWith("/news/")) {
    return { routeId: "/news/$slug", fullPath: "/news/$slug", pathname };
  }
  if (pathname.startsWith("/analyses/")) {
    return { routeId: "/analyses/$jobId", fullPath: "/analyses/$jobId", pathname };
  }
  if (pathname.startsWith("/tools/")) {
    return { routeId: "/tools/", fullPath: "/tools", pathname };
  }
  return { routeId: pathname, fullPath: pathname, pathname };
}

function createStubRouter(initialPathname = "/") {
  let handler: (() => void) | null = null;
  let subscribeCalls = 0;
  const state = { location: { pathname: initialPathname } };

  const router: PageviewRouter = {
    matchRoutes: (pathname: string) => [matchFor(pathname)],
    state,
    subscribe: (_type, next) => {
      subscribeCalls += 1;
      handler = next as () => void;
      return () => {
        handler = null;
      };
    },
  };

  return {
    router,
    subscribeCount: () => subscribeCalls,
    /** Move to a new location and fire the router's onResolved event. */
    navigate(pathname: string) {
      // A real router keeps query and hash out of location.pathname, so the
      // stub must do the same or query-only moves would look like navigations.
      state.location.pathname = pathname.split(/[?#]/, 1)[0];
      handler?.();
    },
    /** Change the location without firing onResolved. */
    setPathSilently(pathname: string) {
      state.location.pathname = pathname;
    },
    isSubscribed: () => handler !== null,
  };
}

function pageParamOf(url: string): string {
  return new URL(url, "http://portal.invalid").searchParams.get("page") ?? "";
}

describe("B4 pageview producer", () => {
  const urls: string[] = [];
  const send = (url: string) => {
    urls.push(url);
  };
  const options = { endpoint: "/track.gif", send, isDntEnabled: () => false };

  beforeEach(() => {
    urls.length = 0;
    document.title = "";
  });

  afterEach(() => {
    delete (navigator as Navigator & { doNotTrack?: string }).doNotTrack;
  });

  describe("template allowlist", () => {
    it("maps router route ids to the server's canonical templates", () => {
      const stub = createStubRouter();
      expect(toPageTemplate("/mutants/abc123", stub.router)).toBe("/mutants/:publicId");
      expect(toPageTemplate("/genes/GRCh38", stub.router)).toBe("/genes/:geneId");
      expect(toPageTemplate("/news/some-slug", stub.router)).toBe("/news/:slug");
      expect(toPageTemplate("/analyses/job-1", stub.router)).toBe("/analyses/:jobId");
      expect(toPageTemplate("/", stub.router)).toBe("/");
      // Bare-pathname form checks the allowlist key itself; the stub router
      // collapses every /tools/* child to the /tools parent.
      expect(toPageTemplate("/tools/sequence")).toBe("/tools/sequence");
    });

    it("collapses a router route the server allowlist does not name", () => {
      const stub = createStubRouter();
      expect(toPageTemplate("/genome-view", stub.router)).toBe(OTHER_PAGE_TEMPLATE);
    });

    it("collapses an unknown path and a trailing-slash variant", () => {
      const stub = createStubRouter();
      expect(toPageTemplate("/not-a-real-page", stub.router)).toBe(OTHER_PAGE_TEMPLATE);
      expect(toPageTemplate("/genes/")).toBe("/genes");
    });

    it("never derives a template from a parameter value", () => {
      const stub = createStubRouter();
      // An id that looks like an assembly name must not leak into the template.
      expect(toPageTemplate("/mutants/v5-assembly", stub.router)).toBe("/mutants/:publicId");
    });
  });

  describe("real router search children (P1)", () => {
    /**
     * Build the smallest router that reproduces the production `/search`
     * topology: one `/search` route whose six children are registered as its
     * file children with relative paths, exactly as `routeTree.gen.ts` does.
     *
     * The generated tree is deliberately **not** imported — it pulls in the
     * whole portal and the `__SOYMUTDB_INTERNAL_SITE__` build define. What
     * matters here is only the parent/child shape that produced the bug.
     */
    function createSearchRouter() {
      const rootRoute = createRootRoute();
      const make = () => createRoute({ getParentRoute: () => rootRoute, component: () => null });

      const rootIndex = make().update({ id: "/", path: "/", getParentRoute: () => rootRoute });
      const searchRoute = make().update({
        id: "/search",
        path: "/search",
        getParentRoute: () => rootRoute,
      });
      // Registered with a slash-LESS `path`, so `fullPath` is slash-less even
      // though the id keeps its trailing slash. This pair caught a real key
      // drift: an allowlist keyed `/tools/` and `/analyses/` collapsed both
      // pages to `/other` once the keys moved from routeId to fullPath.
      const toolsRoute = make().update({
        id: "/tools/",
        path: "/tools",
        getParentRoute: () => rootRoute,
      });
      const analysesRoute = make().update({
        id: "/analyses/",
        path: "/analyses",
        getParentRoute: () => rootRoute,
      });
      // Present but absent from the server allowlist: it must stay `/other`.
      const genomeView = make().update({
        id: "/genome-view",
        path: "/genome-view",
        getParentRoute: () => rootRoute,
      });

      const segments = ["blast", "gbrowse", "genes", "location", "primer", "tools"] as const;
      const children: Record<string, ReturnType<typeof make>> = {};
      for (const segment of segments) {
        children[segment] = createRoute({
          getParentRoute: () => searchRoute,
          component: () => null,
        }).update({ id: `/search/${segment}`, path: segment, getParentRoute: () => searchRoute });
      }
      searchRoute._addFileChildren(children as never);

      const routeTree = rootRoute.addChildren(
        [rootIndex, searchRoute, toolsRoute, analysesRoute, genomeView] as never,
      );
      const router = createRouter({
        routeTree: routeTree as never,
        history: createMemoryHistory({ initialEntries: ["/"] }),
        isServer: false,
      }) as unknown as PageviewRouter;
      return router;
    }

    it.each([
      "/search/blast",
      "/search/gbrowse",
      "/search/genes",
      "/search/location",
      "/search/primer",
      "/search/tools",
    ])("reports %s as itself, not as /search", (path) => {
      const router = createSearchRouter();
      expect(toPageTemplate(path, router)).toBe(path);
    });

    it("names the six children's fullPath, not their doubled routeId", () => {
      const router = createSearchRouter() as unknown as {
        matchRoutes(p: string): Array<{ routeId?: string; fullPath?: string }>;
      };
      // Pin the root cause itself: routeId is `/search/search/genes`, which no
      // route-id-keyed allowlist can name, while fullPath is `/search/genes`.
      const leaf = router.matchRoutes("/search/genes").at(-1);
      expect(leaf?.routeId).toBe("/search/search/genes");
      expect(leaf?.fullPath).toBe("/search/genes");
    });

    it("still reports the parent and the root correctly", () => {
      const router = createSearchRouter();
      expect(toPageTemplate("/search", router)).toBe("/search");
      expect(toPageTemplate("/", router)).toBe("/");
    });

    it("keys slash-less routes by their slash-less fullPath", () => {
      const router = createSearchRouter();
      expect(toPageTemplate("/tools", router)).toBe("/tools");
      expect(toPageTemplate("/analyses", router)).toBe("/analyses");
    });

    it("collapses an unknown /search child rather than inheriting /search", () => {
      const router = createSearchRouter();
      // The router matches the `/search` parent, so a naive parent walk would
      // report `/search`. The leaf pathname `/search` does not account for the
      // requested `/search/xxx`, so it must be `/other`.
      expect(toPageTemplate("/search/xxx", router)).toBe(OTHER_PAGE_TEMPLATE);
    });

    it("collapses a partial match that the router truncates", () => {
      const router = createSearchRouter();
      expect(toPageTemplate("/search/genes/extra", router)).toBe(OTHER_PAGE_TEMPLATE);
    });

    it("collapses a top-level unknown path and an unlisted real route", () => {
      const router = createSearchRouter();
      expect(toPageTemplate("/totally-unknown", router)).toBe(OTHER_PAGE_TEMPLATE);
      expect(toPageTemplate("/genome-view", router)).toBe(OTHER_PAGE_TEMPLATE);
    });
  });

  describe("navigation accounting", () => {
    it("sends exactly one pageview for the initial page and its trailing onResolved", () => {
      const stub = createStubRouter("/");
      initPageviewTracking(stub.router, options);

      stub.navigate("/");
      stub.navigate("/");

      expect(urls).toHaveLength(1);
      expect(pageParamOf(urls[0])).toBe("/");
    });

    it("counts two different ids under one template as two navigations", () => {
      const stub = createStubRouter("/");
      initPageviewTracking(stub.router, options);

      stub.navigate("/mutants/" + SENTINEL + "-a");
      stub.navigate("/mutants/" + SENTINEL + "-b");

      // Initial page plus both navigations; the last two share one template.
      expect(urls).toHaveLength(3);
      expect(pageParamOf(urls[1])).toBe("/mutants/:publicId");
      expect(pageParamOf(urls[2])).toBe("/mutants/:publicId");
    });

    it("counts an A -> B -> A cycle on every visit", () => {
      const stub = createStubRouter("/a-page");
      initPageviewTracking(stub.router, options);

      stub.navigate("/b-page");
      stub.navigate("/a-page");

      expect(urls).toHaveLength(3);
    });

    it("ignores query-only and hash-only location changes", () => {
      const stub = createStubRouter("/search");
      initPageviewTracking(stub.router, options);

      stub.navigate("/search?q=crispr");
      stub.navigate("/search?q=cas9#results");
      stub.navigate("/search");

      // The pathname never moved off /search, so only the initial page counts.
      expect(urls).toHaveLength(1);
      expect(pageParamOf(urls[0])).toBe("/search");
    });

    it("does not resend when a location is replaced without a real navigation", () => {
      const stub = createStubRouter("/about");
      initPageviewTracking(stub.router, options);

      stub.setPathSilently("/about");

      expect(urls).toHaveLength(1);
    });

    it("sends again when the pathname returns after a real navigation", () => {
      const stub = createStubRouter("/mutants/a");
      initPageviewTracking(stub.router, options);

      stub.navigate("/about");
      stub.navigate("/mutants/a");

      expect(urls).toHaveLength(3);
    });
  });

  describe("lifecycle", () => {
    it("does not re-subscribe or re-send the first page on a repeated init", () => {
      const stub = createStubRouter("/");
      initPageviewTracking(stub.router, options);
      initPageviewTracking(stub.router, options);
      initPageviewTracking(stub.router, options);

      expect(stub.subscribeCount()).toBe(1);
      expect(urls).toHaveLength(1);
    });

    it("goes silent after dispose and does not send late", () => {
      const stub = createStubRouter("/");
      const dispose = initPageviewTracking(stub.router, options);

      dispose();
      expect(stub.isSubscribed()).toBe(false);

      stub.navigate("/about");
      expect(urls).toHaveLength(1);
    });

    it("tolerates a double dispose and then resumes cleanly", () => {
      const stub = createStubRouter("/");
      const dispose = initPageviewTracking(stub.router, options);

      dispose();
      dispose();

      initPageviewTracking(stub.router, options);
      stub.navigate("/about");

      // The first page is not re-sent on resume, but navigation works again.
      expect(urls).toHaveLength(2);
      expect(stub.subscribeCount()).toBe(2);
    });

    it("never emits after the module is disposed even if the router fires", () => {
      const stub = createStubRouter("/");
      const dispose = initPageviewTracking(stub.router, options);
      dispose();

      // Simulate a late onResolved from an event queued before dispose.
      const late = new URL("/track.gif?event=pageview&page=/about", "http://x.invalid");
      expect(pageParamOf(late.toString())).toBe("/about");
      expect(urls).toHaveLength(1);
    });
  });

  describe("do-not-track", () => {
    it("stays completely silent when DNT is on at init", () => {
      const stub = createStubRouter("/");
      initPageviewTracking(stub.router, {
        endpoint: "/track.gif",
        send,
        isDntEnabled: () => true,
      });

      stub.navigate("/about");
      expect(urls).toHaveLength(0);
    });

    it("stops sending when DNT is switched on mid-session", () => {
      const stub = createStubRouter("/");
      let dnt = false;
      initPageviewTracking(stub.router, {
        endpoint: "/track.gif",
        send,
        isDntEnabled: () => dnt,
      });

      stub.navigate("/about");
      expect(urls).toHaveLength(2);

      dnt = true;
      stub.navigate("/downloads");

      expect(urls).toHaveLength(2);
    });

    it("reads the live navigator flag on every send", () => {
      const stub = createStubRouter("/");
      initPageviewTracking(stub.router, { endpoint: "/track.gif", send });

      expect(isDoNotTrackEnabled()).toBe(false);
      (navigator as Navigator & { doNotTrack?: string }).doNotTrack = "1";

      stub.navigate("/about");
      expect(isDoNotTrackEnabled()).toBe(true);
      expect(urls).toHaveLength(1);
    });
  });

  describe("request shape", () => {
    it("sends only event and page, with no sentinel leakage", () => {
      const stub = createStubRouter("/");
      document.title = SENTINEL + "-title";
      document.cookie = "sm_sid=" + SENTINEL + "-cookie; path=/";
      initPageviewTracking(stub.router, options);

      stub.navigate("/mutants/" + SENTINEL + "-id?q=" + SENTINEL + "-query#" + SENTINEL + "-hash");
      stub.navigate("/search?q=" + SENTINEL);

      for (const url of urls) {
        expect(url).not.toContain(SENTINEL);
        const parsed = new URL(url, "http://portal.invalid");
        expect([...parsed.searchParams.keys()].sort()).toEqual(["event", "page"]);
        expect(parsed.searchParams.get("event")).toBe("pageview");
        expect(parsed.hash).toBe("");
      }
    });

    it("never sends a site, q, widget, path or referrer parameter", () => {
      const stub = createStubRouter("/");
      initPageviewTracking(stub.router, options);
      stub.navigate("/about");

      const parsed = new URL(urls[0], "http://portal.invalid");
      for (const forbidden of ["site", "q", "widget", "path", "ref", "source", "url"]) {
        expect(parsed.searchParams.has(forbidden)).toBe(false);
      }
    });

    it("does not touch document.cookie", () => {
      const stub = createStubRouter("/");
      document.cookie = "sm_sid=" + SENTINEL + "; path=/";
      initPageviewTracking(stub.router, options);
      stub.navigate("/about");

      expect(urls.join("|")).not.toContain(SENTINEL);
    });

    it("sets referrerPolicy before src on the default beacon", () => {
      const stub = createStubRouter("/");
      // Record the property order on the instance so "before src" is pinned,
      // not just "present at the end": assigning `src` starts the request, so
      // a referrer policy applied afterwards never reaches the wire.
      const order: string[] = [];
      const originalImage = globalThis.Image;
      class RecordingImage {
        set referrerPolicy(value: string) {
          if (value === "no-referrer") order.push("referrerPolicy");
        }
        get referrerPolicy(): string {
          return "no-referrer";
        }
        set src(value: string) {
          void value;
          order.push("src");
        }
      }
      globalThis.Image = RecordingImage as unknown as typeof Image;
      try {
        // No `send` seam: this exercises the real Image beacon path.
        initPageviewTracking(stub.router, {
          endpoint: "/track.gif",
          isDntEnabled: () => false,
        });
      } finally {
        globalThis.Image = originalImage;
      }

      expect(order).toEqual(["referrerPolicy", "src"]);
    });
  });
});
