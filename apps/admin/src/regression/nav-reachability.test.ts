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

import { NAV_SECTIONS, type NavItem } from "../components/admin-sidebar";
import { COMMANDS } from "../components/admin-command-palette";

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

/** Depth-first walk over the sidebar tree; submenus carry no path of their own. */
function navEntries(items: NavItem[]): NavItem[] {
  return items.flatMap((item) => [item, ...(item.children ? navEntries(item.children) : [])]);
}

const NAV_ITEMS = NAV_SECTIONS.flatMap((section) => navEntries(section.items));

/** Paths an operator reaches from the sidebar today. */
const NAV_PATHS = new Set(NAV_ITEMS.map((item) => item.path).filter((path): path is string => Boolean(path)));

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
  "/page-builder/$pageId",
  "/widgets",
  "/widgets/$name",
  "/widget-preview",
  "/widget-health",
  "/layout",
  "/resource-catalog",
]);

/**
 * Path -> the lazy component the router renders for it, read from the same
 * `createRoute` literals the reachability check above already parses.
 *
 * `LegacyUnavailablePage` is the console's explicit "nothing lives here" screen.
 * Reachability is not enough on its own: an entry can be perfectly reachable and
 * still be a dead end. `/resource-catalog` shipped in the sidebar and as the
 * dashboard's primary call-to-action while resolving to that page, which is how
 * a reachable-but-useless destination survives every "is it in the nav?" guard.
 */
function routerComponents(): Map<string, string> {
  const components = new Map<string, string>();
  for (const block of appSource.split(/createRoute\(\{/)) {
    const path = /\bpath:\s*"([^"]+)"/.exec(block)?.[1];
    const component = /component:\s*\(\)\s*=>\s*withSuspense\((\w+)\)/.exec(block)?.[1];
    if (path && component) components.set(path, component);
  }
  return components;
}

const UNAVAILABLE_COMPONENT = "LegacyUnavailablePage";

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

  it("resolves each sidebar entry to the component the router renders", () => {
    const components = routerComponents();
    expect(components.size).toBeGreaterThan(20);
    expect(components.get("/")).toBe("DashboardPage");
    // The retired routes are the ones this guard exists for, so the parser has
    // to see them before it can keep them out of the menu.
    expect(components.get("/resource-catalog")).toBe(UNAVAILABLE_COMPONENT);
    expect(components.get("/widgets")).toBe(UNAVAILABLE_COMPONENT);
  });

  it("keeps every sidebar entry off the unavailable page", () => {
    const components = routerComponents();
    const deadEnds = [...NAV_PATHS]
      .filter((path) => components.get(path) === UNAVAILABLE_COMPONENT)
      .sort();
    expect(deadEnds).toEqual([]);
  });

  it("keeps every command-palette destination on a real, live route", () => {
    const paths = new Set(routerPaths());
    const components = routerComponents();
    const routes = COMMANDS.filter((command) => command.kind === "route");
    expect(routes.length).toBeGreaterThan(0);
    for (const command of routes) {
      expect(paths.has(command.path), command.id).toBe(true);
      expect(components.get(command.path), command.id).not.toBe(UNAVAILABLE_COMPONENT);
    }
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
    for (const item of NAV_ITEMS) {
      if (item.path === "/") continue; // the dashboard is allowed once per section list
      if (item.path) seen.push(item.path);
    }
    expect(seen.filter((path, index) => seen.indexOf(path) !== index)).toEqual([]);
  });

  it("renders multi-level navigation without placeholder parents", () => {
    // A submenu exists to group destinations, so it must have children and no
    // path of its own; a leaf must have a path and no children.
    const broken: string[] = [];
    for (const item of NAV_ITEMS) {
      if (item.children?.length && item.path) broken.push(`${item.label}: submenu with a path`);
      if (!item.children?.length && !item.path) broken.push(`${item.label}: leaf without a path`);
    }
    expect(broken).toEqual([]);
    expect(
      NAV_SECTIONS.some((section) =>
        section.items.some((item) => (item.children?.length ?? 0) > 0),
      ),
    ).toBe(true);
  });

  it("fails when a shipped destination is dropped from the sidebar (ablation)", () => {
    // Removing `/media` must be detected; if it is not, the real assertions above
    // cannot distinguish "checked" from "never looked".
    const withoutMedia = new Set(NAV_PATHS);
    withoutMedia.delete("/media");
    expect(missingFromNav(routerPaths(), withoutMedia)).toEqual(["/media"]);
  });
});