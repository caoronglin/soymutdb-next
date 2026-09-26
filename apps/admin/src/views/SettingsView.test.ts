// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mountAdminView } from "../test/support";

import { adminSettingsApi } from "@soymutdb/api-client";
import SettingsView from "./SettingsView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    adminSettingsApi: {
      schema: vi.fn(),
      get: vi.fn(),
      validate: vi.fn(),
      patch: vi.fn(),
      history: vi.fn(),
      rollback: vi.fn(),
    },
  };
});

const FIELD = {
  kind: "string" as const,
  default: "",
  permission: "administrator" as const,
  scope: "global" as const,
  hot_reload: true,
  redaction: "none" as const,
  requires_approval: false,
  allowed_values: [],
  allowed_url_hosts: [],
  minimum: null,
  maximum: null,
  max_length: 120,
};

const SCHEMA = {
  version: 1 as const,
  sections: {
    general: { fields: { siteName: FIELD } },
    cdn: { fields: { url: FIELD } },
  },
};

beforeEach(() => {
  vi.mocked(adminSettingsApi.schema)
    .mockReset()
    .mockResolvedValue(SCHEMA as never);
  vi.mocked(adminSettingsApi.get)
    .mockReset()
    .mockImplementation((section: string) =>
      Promise.resolve({ section, version: 1, values: {} } as never),
    );
});

describe("SettingsView section routing", () => {
  it("opens a registered ?section from the schema", async () => {
    const { wrapper, router } = mountAdminView(SettingsView, { path: "/settings" });
    await flushPromises();

    await router.push({ path: "/settings", query: { section: "cdn" } });
    await flushPromises();

    expect(wrapper.find('[data-testid="settings-section-missing"]').exists()).toBe(false);
    expect(vi.mocked(adminSettingsApi.get)).toHaveBeenLastCalledWith("cdn");
    wrapper.unmount();
  });

  it("renders a documented unavailable state for an unregistered section", async () => {
    const { wrapper, router } = mountAdminView(SettingsView, { path: "/settings" });
    await flushPromises();

    await router.push({ path: "/settings", query: { section: "not-a-section" } });
    await flushPromises();

    expect(wrapper.find('[data-testid="settings-section-missing"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="settings-section-missing"]').text()).toContain("not-a-section");
    // Never silently open another registered section in its place after the
    // requested one was rejected.
    wrapper.unmount();
  });

  it("falls back to the first registered section when no section is requested", async () => {
    const { wrapper } = mountAdminView(SettingsView, { path: "/settings" });
    await flushPromises();

    expect(wrapper.find('[data-testid="settings-section-missing"]').exists()).toBe(false);
    expect(vi.mocked(adminSettingsApi.get)).toHaveBeenCalledWith("general");
    wrapper.unmount();
  });
});
