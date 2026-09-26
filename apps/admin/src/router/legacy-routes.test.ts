// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

// The route table imports real views, whose design-system import must not pull
// the Antdv runtime into this test (same facade mock as ../test/support).
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

import LegacyUnavailableView from "../views/LegacyUnavailableView.vue";
import { ADMIN_ROUTES } from "./index";
import { createMemoryHistory, createRouter } from "vue-router";

// Resolve against a memory router built from the same route table; the app's
// singleton uses web history, which is irrelevant here and would need jsdom
// navigation. resolve() follows redirects without running guards.
const router = createRouter({
  history: createMemoryHistory(),
  routes: [...ADMIN_ROUTES],
});

/**
 * Legacy React-console deep links must stay reachable.
 *
 * The migration plan allows two outcomes and forbids two others: a redirect to
 * the restored equivalent, or an explicit "not restored" page — never a bare
 * 404 and never an empty shell that reads as working.
 */
describe("legacy admin deep links", () => {
  it("redirects restored equivalents to the current route and state", async () => {
    // resolve() only matches; redirects are followed during navigation.
    await router.push("/settings/site");
    expect(router.currentRoute.value.path).toBe("/settings/brand");

    await router.push("/settings/security");
    expect(router.currentRoute.value.path).toBe("/settings");
    expect(router.currentRoute.value.query.section).toBe("security");

    await router.push("/news/new");
    expect(router.currentRoute.value.path).toBe("/news");
    expect(router.currentRoute.value.query.new).toBe("1");

    await router.push("/news/trash");
    expect(router.currentRoute.value.path).toBe("/news");
    expect(router.currentRoute.value.query.status).toBe("archived");

    await router.push("/news/article-7");
    expect(router.currentRoute.value.path).toBe("/news");
    expect(router.currentRoute.value.query.edit).toBe("article-7");
  });

  it("lands unported workflows on the explicit unavailable page", () => {
    for (const path of [
      "/resource-catalog",
      "/content",
      "/content/pages",
      "/content/legacy",
      "/settings/legacy",
      "/settings/appearance",
      "/settings/integrations",
      "/settings/localization",
      "/settings/advanced",
      "/analytics-settings",
      "/widgets",
      "/widgets/import-throughput",
      "/layout",
      "/widget-preview",
      "/widget-health",
      "/page-builder",
      "/page-builder/page-1",
    ]) {
      const resolved = router.resolve(path);
      expect(resolved.matched.at(-1)?.components?.default, path).toBe(LegacyUnavailableView);
    }
  });

  it("restores the import create and detail deep links (P1-06)", () => {
    const create = router.resolve("/imports/new");
    expect(create.name).toBe("import-create");
    const detail = router.resolve("/imports/42");
    expect(detail.name).toBe("import-detail");
    expect(detail.params.taskId).toBe("42");
  });

  it("keeps the catch-all for paths that were never console routes", () => {
    const unknown = router.resolve("/definitely-not-a-console-route");
    expect(unknown.name).toBe("not-found");
    expect(unknown.matched.at(-1)?.components?.default).not.toBe(LegacyUnavailableView);
  });
});
