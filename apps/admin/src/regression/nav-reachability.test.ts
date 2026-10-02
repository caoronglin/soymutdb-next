// ABLATION — an admin destination that exists in the router but not in the sidebar.
//
// Invariant: every non-parameterised admin route is reachable from `NAV_SECTIONS`, the single
// navigation source `__root.tsx` hands to ProLayout. Detail routes (`/news/$id`,
// `/imports/$taskId`) are reachable *through* their list route and are exempt.
//
// Why it matters: this guard existed in the Vue tree (`nav-reachability.test.ts`) and was deleted
// with it. Without it a route can ship wired but invisible — the page loads, the sidebar has no
// entry, and an operator only finds the feature by typing the URL.
//
// Ablation proof: dropping one synthetic entry makes this guard fail, so a green run means the
// check is load-bearing rather than vacuous.
//
// If this is RED: an operator cannot reach a shipped feature from the console.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { NAV_SECTIONS } from "../components/admin-sidebar";

const here = dirname(fileURLToPath(import.meta.url));
const appSource = readFileSync(join(here, "../App.tsx"), "utf8");

/** Every literal path passed to `createRoute` in the admin router. */
function routerPaths(): string[] {
  const paths = new Set<string>();
  for (const match of appSource.matchAll(/\bpath:\s*"([^"]+)"/g)) {
    paths.add(match[1]);
  }
  return [...paths].sort();
}

/** Paths an operator reaches from the sidebar today. */
const NAV_PATHS = new Set(NAV_SECTIONS.flatMap((section) => section.items.map((item) => item.path)));

/**
 * Routes that are intentionally not sidebar entries: the login screen (no console
 * behind it), the redirect/alias routes that keep a retired deep link alive, and the
 * ADR-0009 retirements that deliberately resolve to an "unavailable" page.
 */
const NOT_IN_NAV = new Set([
  "/login",
  "/content",
  "/imports/new",
  "/news/new",
  "/news/trash",
  "/settings/site",
  "/settings/legacy",
  "/table-views",
  "/page-builder",
  "/page-builder/$pageId",
  "/widgets",
  "/widgets/$name",
  "/widget-preview",
  "/widget-health",
  "/layout",
]);

function isDetailRoute(path: string): boolean {
  return path.includes("$");
}

/** `/settings/security` is reached as a tab under the `/settings` entry. */
function hasNavAncestor(path: string, navPaths: Set<string>): boolean {
  const segments = path.split("/").filter(Boolean);
  for (let i = 1; i < segments.length; i += 1) {
    if (navPaths.has(`/${segments.slice(0, i).join("/")}`)) return true;
  }
  return false;
}

function missingFromNav(paths: string[], navPaths: Set<string>): string[] {
  return paths.filter(
    (path) =>
      !navPaths.has(path) &&
      !isDetailRoute(path) &&
      !hasNavAncestor(path, navPaths) &&
      !NOT_IN_NAV.has(path),
  );
}

describe("admin navigation reachability", () => {
  it("parses the router path literals it depends on", () => {
    // If this fails the guard below is vacuous, which is worse than no guard.
    expect(routerPaths().length).toBeGreaterThan(20);
    expect(routerPaths()).toContain("/content/pages");
  });

  it("puts every shipped admin destination in the sidebar", () => {
    expect(missingFromNav(routerPaths(), NAV_PATHS)).toEqual([]);
  });

  it("keeps sidebar entries pointing at real routes", () => {
    const paths = new Set(routerPaths());
    const dangling = [...NAV_PATHS].filter((path) => !paths.has(path)).sort();
    expect(dangling).toEqual([]);
  });

  it("has no duplicate sidebar entries", () => {
    const seen: string[] = [];
    for (const section of NAV_SECTIONS) {
      for (const item of section.items) {
        if (item.path === "/") continue; // the dashboard is allowed once per section list
        seen.push(item.path);
      }
    }
    expect(seen.filter((path, index) => seen.indexOf(path) !== index)).toEqual([]);
  });

  it("fails when a shipped destination is dropped from the sidebar (ablation)", () => {
    // Removing `/media` must be detected; if it is not, the real assertions above
    // cannot distinguish "checked" from "never looked".
    const withoutMedia = new Set(NAV_PATHS);
    withoutMedia.delete("/media");
    expect(missingFromNav(routerPaths(), withoutMedia)).toEqual(["/media"]);
  });
});