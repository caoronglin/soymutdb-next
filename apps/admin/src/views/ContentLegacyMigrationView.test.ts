// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mountAdminView } from "../test/support";

import {
  dryRunStaticPageMigration,
  type StaticPageMigrationDryRunReport,
} from "@soymutdb/api-client";
import ContentLegacyMigrationView from "./ContentLegacyMigrationView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, dryRunStaticPageMigration: vi.fn() };
});

const REPORT: StaticPageMigrationDryRunReport = {
  dry_run: true,
  created: 1,
  skipped: 1,
  invalid: 0,
  items: [
    {
      static_page_id: 1,
      slug: "about",
      route: "/pages/about",
      outcome: "created",
      error_code: null,
      message: null,
    },
    {
      static_page_id: 2,
      slug: "help",
      route: "/pages/help",
      outcome: "skipped",
      error_code: "target_route_exists",
      message: "A Page Builder page already exists for this route.",
    },
  ],
};

beforeEach(() => {
  vi.mocked(dryRunStaticPageMigration).mockReset().mockResolvedValue(REPORT);
});

describe("ContentLegacyMigrationView", () => {
  it("does not call the endpoint until the operator requests a preview", async () => {
    const { wrapper } = mountAdminView(ContentLegacyMigrationView, { path: "/content/legacy" });
    await flushPromises();

    expect(vi.mocked(dryRunStaticPageMigration)).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="migration-report"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders the server-owned dry-run report after preview", async () => {
    const { wrapper } = mountAdminView(ContentLegacyMigrationView, { path: "/content/legacy" });
    await flushPromises();

    await wrapper.get('[data-testid="migration-run"]').trigger("click");
    await flushPromises();

    expect(vi.mocked(dryRunStaticPageMigration)).toHaveBeenCalledWith({});
    expect(wrapper.findAll('[data-testid="migration-item"]')).toHaveLength(2);
    expect(wrapper.get('[data-testid="migration-report"]').text()).toContain("/pages/about");
    wrapper.unmount();
  });

  it("surfaces a failure without inventing report data", async () => {
    vi.mocked(dryRunStaticPageMigration).mockRejectedValueOnce(new Error("boom"));
    const { wrapper } = mountAdminView(ContentLegacyMigrationView, { path: "/content/legacy" });
    await flushPromises();

    await wrapper.get('[data-testid="migration-run"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="migration-error"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="migration-report"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
