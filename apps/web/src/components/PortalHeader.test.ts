// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getSiteBranding } from "@soymutdb/api-client";
import { mountPortalView } from "../test/mount-portal-view";
import PortalHeader from "./PortalHeader.vue";
import { resolveBrandName } from "../lib/branding";
import { setLanguage } from "../lib/i18n";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getSiteBranding: vi.fn() };
});

const mockedBranding = vi.mocked(getSiteBranding);

const BRAND = {
  variant: "external" as const,
  name_zh: "大豆突变体数据库",
  name_en: "SoyMutDB",
  icon_url: null,
};

beforeEach(() => {
  setLanguage("en");
  mockedBranding.mockReset().mockResolvedValue(BRAND);
});

describe("resolveBrandName", () => {
  it("selects the language field and falls back to the other language", () => {
    expect(resolveBrandName(BRAND, "en")).toBe("SoyMutDB");
    expect(resolveBrandName(BRAND, "zh")).toBe("大豆突变体数据库");
    expect(resolveBrandName({ ...BRAND, name_zh: "" }, "zh")).toBe("SoyMutDB");
    expect(resolveBrandName({ ...BRAND, name_en: "  " }, "en")).toBe("大豆突变体数据库");
  });

  it("keeps the build default when the snapshot is missing or blank", () => {
    expect(resolveBrandName(undefined, "en")).toBe("SoyMutDB");
    expect(resolveBrandName({ ...BRAND, name_en: "", name_zh: "" }, "en")).toBe("SoyMutDB");
  });
});

describe("PortalHeader branding", () => {
  it("renders the fetched name for the active language", async () => {
    const { wrapper } = mountPortalView(PortalHeader, { path: "/" });
    await flushPromises();

    expect(mockedBranding).toHaveBeenCalledWith("external");
    expect(wrapper.get('[data-testid="portal-brand-name"]').text()).toBe("SoyMutDB");

    setLanguage("zh");
    await flushPromises();
    expect(wrapper.get('[data-testid="portal-brand-name"]').text()).toBe("大豆突变体数据库");
    wrapper.unmount();
  });

  it("falls back to the built-in wordmark when branding cannot load", async () => {
    mockedBranding.mockRejectedValue(new Error("offline"));
    const { wrapper } = mountPortalView(PortalHeader, { path: "/" });
    await flushPromises();

    expect(wrapper.get('[data-testid="portal-brand-name"]').text()).toBe("SoyMutDB");
    expect(wrapper.find('[data-testid="portal-brand-icon"]').exists()).toBe(false);
    wrapper.unmount();
  });
});

describe("PortalHeader feature gating (core-only deployment)", () => {
  it("hides the genome-browser entry when VITE_JBROWSE_ENABLED=0", async () => {
    vi.stubEnv("VITE_JBROWSE_ENABLED", "0");
    mockedBranding.mockResolvedValue(BRAND);
    const { wrapper } = mountPortalView(PortalHeader, { path: "/" });
    await flushPromises();

    await wrapper.get('[data-testid="nav-group-explore"]').trigger("click");
    await flushPromises();

    expect(wrapper.html()).not.toContain('href="/browser"');
    // The core entries stay present.
    expect(wrapper.html()).toContain('href="/genes"');
    vi.unstubAllEnvs();
    wrapper.unmount();
  });

  it("keeps the genome-browser entry by default", async () => {
    vi.stubEnv("VITE_JBROWSE_ENABLED", "1");
    mockedBranding.mockResolvedValue(BRAND);
    const { wrapper } = mountPortalView(PortalHeader, { path: "/" });
    await flushPromises();

    await wrapper.get('[data-testid="nav-group-explore"]').trigger("click");
    await flushPromises();

    expect(wrapper.html()).toContain('href="/browser"');
    vi.unstubAllEnvs();
    wrapper.unmount();
  });
});
