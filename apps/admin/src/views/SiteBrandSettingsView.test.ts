// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mountAdminView } from "../test/support";

import {
  ApiError,
  getAdminSiteBranding,
  patchAdminSiteBranding,
  type AdminSiteBranding,
} from "@soymutdb/api-client";
import SiteBrandSettingsView from "./SiteBrandSettingsView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getAdminSiteBranding: vi.fn(),
    patchAdminSiteBranding: vi.fn(),
  };
});

const EXTERNAL: AdminSiteBranding = {
  variant: "external",
  version: 3,
  values: {
    name_zh: "大豆突变体数据库",
    name_en: "SoyMutDB",
    icon_url: "https://media.example.org/uploads/icon.png",
  },
};

const INTERNAL: AdminSiteBranding = {
  variant: "internal",
  version: 1,
  values: { name_zh: "大豆突变体数据库（内网）", name_en: "SoyMutDB Internal", icon_url: null },
};

const mockedGet = vi.mocked(getAdminSiteBranding);
const mockedPatch = vi.mocked(patchAdminSiteBranding);

beforeEach(() => {
  mockedGet.mockReset().mockImplementation(async (variant = "external") =>
    variant === "internal" ? INTERNAL : EXTERNAL,
  );
  mockedPatch.mockReset();
});

describe("SiteBrandSettingsView", () => {
  it("loads the explicit external variant and shows its revision", async () => {
    const { wrapper } = mountAdminView(SiteBrandSettingsView, { path: "/settings/brand" });
    await flushPromises();

    expect(mockedGet).toHaveBeenCalledWith("external");
    expect((wrapper.get('[data-testid="brand-name-zh"]').element as HTMLInputElement).value).toBe(
      "大豆突变体数据库",
    );
    expect(wrapper.get('[data-testid="brand-form"]').text()).toContain("3");
    wrapper.unmount();
  });

  it("reloads values when the operator switches variants", async () => {
    const { wrapper } = mountAdminView(SiteBrandSettingsView, { path: "/settings/brand" });
    await flushPromises();

    await wrapper.get('[data-testid="brand-variant-internal"]').trigger("click");
    await flushPromises();

    expect(mockedGet).toHaveBeenCalledWith("internal");
    expect((wrapper.get('[data-testid="brand-name-en"]').element as HTMLInputElement).value).toBe(
      "SoyMutDB Internal",
    );
    expect(wrapper.find('[data-testid="brand-icon-empty"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("saves the loaded revision and leaves an untouched icon alone", async () => {
    mockedPatch.mockResolvedValue({ ...EXTERNAL, version: 4 });
    const { wrapper } = mountAdminView(SiteBrandSettingsView, { path: "/settings/brand" });
    await flushPromises();

    await wrapper.get('[data-testid="brand-name-en"]').setValue("SoyMutDB Portal");
    await wrapper.get('[data-testid="brand-form"]').trigger("submit");
    await flushPromises();

    expect(mockedPatch).toHaveBeenCalledWith("external", 3, {
      name_zh: "大豆突变体数据库",
      name_en: "SoyMutDB Portal",
    });
    wrapper.unmount();
  });

  it("clears the icon with an explicit null", async () => {
    mockedPatch.mockResolvedValue({ ...EXTERNAL, version: 4, values: { ...EXTERNAL.values, icon_url: null } });
    const { wrapper } = mountAdminView(SiteBrandSettingsView, { path: "/settings/brand" });
    await flushPromises();

    await wrapper.get('[data-testid="brand-icon-clear"]').trigger("click");
    await wrapper.get('[data-testid="brand-form"]').trigger("submit");
    await flushPromises();

    expect(mockedPatch).toHaveBeenCalledWith(
      "external",
      3,
      expect.objectContaining({ icon_url: null }),
    );
    wrapper.unmount();
  });

  it("reports a version conflict and reloads instead of overwriting", async () => {
    mockedPatch.mockRejectedValue(
      new ApiError("Settings document changed", 409, "SETTINGS_VERSION_CONFLICT"),
    );
    const { wrapper } = mountAdminView(SiteBrandSettingsView, { path: "/settings/brand" });
    await flushPromises();

    await wrapper.get('[data-testid="brand-form"]').trigger("submit");
    await flushPromises();

    expect(wrapper.get('[data-testid="brand-conflict"]').text()).toContain("saved a newer version");
    expect(wrapper.find('[data-testid="brand-notice"]').exists()).toBe(false);
    // The conflict path refetches so the next save carries the stored revision.
    expect(mockedGet.mock.calls.length).toBeGreaterThan(1);
    wrapper.unmount();
  });
});
