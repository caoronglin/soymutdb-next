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

import AnalyticsSettingsView from "../views/AnalyticsSettingsView.vue";
import ContentLegacyMigrationView from "../views/ContentLegacyMigrationView.vue";
import LegacyUnavailableView from "../views/LegacyUnavailableView.vue";
import StaticPagesView from "../views/StaticPagesView.vue";
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
    expect(router.currentRoute.value.query.status).toBe("trash");

    await router.push("/news/article-7");
    expect(router.currentRoute.value.path).toBe("/news");
    expect(router.currentRoute.value.query.edit).toBe("article-7");
  });

  it("maps each settings sub-page onto a registered schema section", async () => {
    const expected: Array<[string, string]> = [
      ["/settings/appearance", "general"],
      ["/settings/integrations", "cdn"],
      ["/settings/localization", "general"],
      ["/settings/advanced", "data"],
    ];
    for (const [path, section] of expected) {
      await router.push(path);
      expect(router.currentRoute.value.path, path).toBe("/settings");
      expect(router.currentRoute.value.query.section, path).toBe(section);
    }

    // The monolithic legacy form is the overview: every registered section is
    // reachable and the first one opens by default.
    await router.push("/settings/legacy");
    expect(router.currentRoute.value.path).toBe("/settings");
    expect(router.currentRoute.value.query.section).toBeUndefined();
  });

  it("exposes the content and analytics routes as real data-backed views", () => {
    expect(router.resolve("/content").name).toBe("content");
    expect(router.resolve("/content").matched.at(-1)?.components?.default).toBe(StaticPagesView);

    expect(router.resolve("/content/pages").name).toBe("content-pages");
    expect(router.resolve("/content/pages").matched.at(-1)?.components?.default).toBe(StaticPagesView);

    expect(router.resolve("/content/legacy").name).toBe("content-legacy");
    expect(router.resolve("/content/legacy").matched.at(-1)?.components?.default).toBe(
      ContentLegacyMigrationView,
    );

    expect(router.resolve("/analytics-settings").name).toBe("analytics-settings");
    expect(router.resolve("/analytics-settings").matched.at(-1)?.components?.default).toBe(
      AnalyticsSettingsView,
    );
  });

  it("redirects a /content/pages/:pageId deep link into the editor", async () => {
    await router.push("/content/pages/42");
    expect(router.currentRoute.value.path).toBe("/content");
    expect(router.currentRoute.value.query.edit).toBe("42");
  });

  it("lands unbacked and ADR-0009-retired workflows on the explicit unavailable page", () => {
    for (const path of [
      "/resource-catalog",
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
