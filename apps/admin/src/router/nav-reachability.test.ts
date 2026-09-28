// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

// Views import the design-system facade; stub it so this table-level test never
// boots the Antdv runtime (same approach as ./legacy-routes.test.ts).
vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  createThemeConfig: () => ({}),
  Button: {
    props: ["disabled", "type", "htmlType", "size"],
    emits: ["click"],
    template: "<button><slot /></button>",
  },
  Tag: { props: ["color"], template: "<span><slot /></span>" },
  Table: { template: "<table><slot /></table>" },
}));

import { ADMIN_NAV_SECTIONS, ADMIN_PAGE_TITLES } from "../lib/admin-nav";
import { ADMIN_ROUTES } from "./index";

const router = createRouter({ history: createMemoryHistory(), routes: [...ADMIN_ROUTES] });

/**
 * Every console destination must be reachable.
 *
 * The migration brief requires each route — including the ones a sidebar or a
 * top-bar title points at — to resolve to a real record, so a link can never
 * land on the catch-all 404. Views are already covered for their loading /
 * error / empty branches by their own tests; this one guards the table itself.
 */
describe("admin route reachability", () => {
  it("gives every route record a component or a redirect", () => {
    for (const route of ADMIN_ROUTES) {
      const hasTarget = Boolean(route.component) || Boolean(route.redirect);
      expect(hasTarget, String(route.path)).toBe(true);
    }
  });

  it("resolves every sidebar entry to a non-catch-all route", () => {
    for (const section of ADMIN_NAV_SECTIONS) {
      for (const item of section.items) {
        const resolved = router.resolve(item.path);
        expect(resolved.name, item.path).not.toBe("not-found");
        expect(resolved.matched.length, item.path).toBeGreaterThan(0);
      }
    }
  });

  it("resolves every top-bar title path to a non-catch-all route", () => {
    for (const entry of ADMIN_PAGE_TITLES) {
      const resolved = router.resolve(entry.path);
      expect(resolved.name, entry.path).not.toBe("not-found");
    }
  });

  it("keeps the gene jump target documented as a known console gap", () => {
    // The command palette opens `/genes/<id>`; the public gene detail page lives
    // in apps/web, so inside the console that path currently falls through to
    // the catch-all. Asserted here so the gap is visible rather than assumed.
    expect(router.resolve("/genes/Glyma.01G000100").name).toBe("not-found");
  });
});
