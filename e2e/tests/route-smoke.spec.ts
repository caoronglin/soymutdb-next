/**
 * Route smoke: every public portal route mounts without a crash.
 *
 * The focused specs cover the search/entity flows with deterministic mocks; the
 * other ~30 routes were only covered by typecheck/build and had no browser
 * evidence. This test walks the whole public route table on the built artifact
 * and fails on a pageerror, an unexpected console error, an empty `#root`, or
 * React's error boundary text. API calls are expected to fail offline (the
 * artifact bakes an absolute API origin), so network errors are tolerated;
 * crashes and rendering failures are not.
 */
import { test, expect, type Page } from "@playwright/test";
import { TOLERATED_CONSOLE_ERRORS, waitForAppReady } from "./helpers";

const ROUTES = [
  "/",
  "/about",
  "/analyses",
  "/analyses/fastp",
  "/analyses/scanpy",
  "/analyses/does-not-exist",
  "/analytics",
  "/blast",
  "/browser",
  "/compare",
  "/downloads",
  "/genes",
  "/genes/Glyma.01G000100",
  "/genome-view",
  "/guide",
  "/help",
  "/login",
  "/mutants",
  "/mutants/SMDB-00001",
  "/news",
  "/news/hello",
  "/publications",
  "/search",
  "/search/blast",
  "/search/gbrowse",
  "/search/genes?q=Glyma.01G000100&run=1",
  "/search/location",
  "/search/primer",
  "/search/tools",
  "/seed-request",
  "/sra",
  "/tools",
  "/tools/enrichment",
  "/tools/exppattern",
  "/tools/seqfetch",
  "/variants",
];

interface RouteState {
  pageErrors: string[];
  consoleErrors: string[];
  crashed: boolean;
  emptyRoot: boolean;
}

/** Attach listeners once; callers mark the current route before navigating. */
function attachErrorTracking(page: Page) {
  const byRoute = new Map<string, RouteState>();
  let current = "";
  const ensure = (route: string): RouteState => {
    let state = byRoute.get(route);
    if (!state) {
      state = { pageErrors: [], consoleErrors: [], crashed: false, emptyRoot: false };
      byRoute.set(route, state);
    }
    return state;
  };
  page.on("pageerror", (error) => ensure(current).pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (TOLERATED_CONSOLE_ERRORS.some((pattern) => pattern.test(text))) return;
    ensure(current).consoleErrors.push(text);
  });
  return {
    enter(route: string): void {
      current = route;
      ensure(route);
    },
    state(route: string): RouteState {
      return ensure(route);
    },
    broken(): Record<string, RouteState> {
      return Object.fromEntries(
        [...byRoute.entries()].filter(
          ([, value]) =>
            value.pageErrors.length > 0 ||
            value.consoleErrors.length > 0 ||
            value.crashed ||
            value.emptyRoot,
        ),
      );
    },
  };
}

async function crawl(page: Page, baseURL: string | undefined, lang: "en" | "zh") {
  test.setTimeout(300_000);
  await page.addInitScript((locale: string) => {
    localStorage.setItem("soymutdb_lang", locale);
  }, lang);
  const tracking = attachErrorTracking(page);

  for (const route of ROUTES) {
    tracking.enter(route);
    const url = new URL(route.replace(/^\//, ""), baseURL).toString();
    await page.goto(url, { waitUntil: "load" });
    await waitForAppReady(page);
    const state = tracking.state(route);
    const rendered = await page.evaluate(() => ({
      crashed: /Unexpected Application Error/i.test(document.body.innerText),
      rootChildren: document.querySelector("#root")?.childElementCount ?? 0,
    }));
    state.crashed = rendered.crashed;
    state.emptyRoot = rendered.rootChildren === 0;
    expect(rendered.crashed, `route ${route} rendered the React error boundary`).toBe(false);
    expect(rendered.rootChildren, `route ${route} left #root empty`).toBeGreaterThan(0);
  }

  const broken = tracking.broken();
  expect(broken, `public routes with console/page errors (${lang}): ${Object.keys(broken)}`).toEqual({});
}

test("every public route mounts without a crash (en)", async ({ page, baseURL }) => {
  await crawl(page, baseURL, "en");
});

test("every public route mounts without a crash (zh)", async ({ page, baseURL }) => {
  await crawl(page, baseURL, "zh");
});
