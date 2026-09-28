// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getCurrentUser, getSiteBranding, fetchUnreadCount, getSiteContent } from "@soymutdb/api-client";
import { mountPortalView } from "../test/mount-portal-view";
import PortalHeader from "./PortalHeader.vue";
import { resolveBrandName } from "../lib/branding";
import { __resetSessionStateForTests, markSessionEstablished } from "../lib/current-user";
import { setLanguage, t } from "../lib/i18n";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getSiteBranding: vi.fn(),
    getCurrentUser: vi.fn(),
    fetchUnreadCount: vi.fn(),
    getSiteContent: vi.fn(),
  };
});

const mockedBranding = vi.mocked(getSiteBranding);
const mockedCurrentUser = vi.mocked(getCurrentUser);
const mockedUnread = vi.mocked(fetchUnreadCount);
const mockedSiteContent = vi.mocked(getSiteContent);

const BRAND = {
  variant: "external" as const,
  name_zh: "大豆突变体数据库",
  name_en: "SoyMutDB",
  icon_url: null,
};

beforeEach(() => {
  setLanguage("en");
  // No session is established by default, so `useCurrentUser` never probes
  // /auth/me; the bell therefore renders nothing, which is the behaviour the
  // pre-existing header assertions were written against.
  __resetSessionStateForTests();
  mockedBranding.mockReset().mockResolvedValue(BRAND);
  mockedCurrentUser.mockReset().mockRejectedValue(new Error("401"));
  mockedUnread.mockReset().mockResolvedValue({ unread_count: 0 });
  mockedSiteContent.mockReset().mockResolvedValue({});
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

describe("PortalHeader notification bell", () => {
  it("renders no bell for an anonymous visitor", async () => {
    const { wrapper } = mountPortalView(PortalHeader, { path: "/" });
    await flushPromises();

    expect(wrapper.find('[data-testid="portal-notifications-toggle"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders the bell with the unread badge next to the language switch when signed in", async () => {
    // The probe is gated on a restored session (see lib/current-user.ts).
    markSessionEstablished(true);
    mockedCurrentUser.mockResolvedValue({
      id: "u1",
      email: "u@example.com",
      username: "u",
      role_name: "viewer",
      is_superuser: false,
      is_active: true,
    } as never);
    mockedUnread.mockResolvedValue({ unread_count: 5 });

    const { wrapper } = mountPortalView(PortalHeader, { path: "/" });
    await flushPromises();

    const bell = wrapper.get('[data-testid="portal-notifications-toggle"]');
    expect(wrapper.get('[data-testid="portal-notifications-count"]').text()).toBe("5");
    // Placement contract: the bell sits in the right-hand icon cluster,
    // immediately before the language switch.
    const cluster = bell.element.parentElement?.parentElement;
    expect(cluster?.querySelector('[data-testid="language-switch"]')).not.toBeNull();
    wrapper.unmount();
  });
});

describe("PortalHeader editable navigation labels", () => {
  it("renders a stored nav override and keeps the localized label otherwise", async () => {
    mockedSiteContent.mockResolvedValue({ "nav.explore": "探索OVERRIDE" });

    const { wrapper } = mountPortalView(PortalHeader, { path: "/" });
    await flushPromises();

    expect(mockedSiteContent).toHaveBeenCalledWith("external", { onlyOverrides: true });
    expect(wrapper.get('[data-testid="nav-group-explore"]').text()).toContain("探索OVERRIDE");
    // A registered key with no stored row keeps today's i18n label.
    expect(wrapper.get('[data-testid="nav-link-downloads"]').text()).toBe(t("nav.downloads"));
    wrapper.unmount();
  });

  it("keeps unregistered nav labels i18n-only", async () => {
    mockedSiteContent.mockResolvedValue({ "nav.mutantLines": "should not apply" });

    const { wrapper } = mountPortalView(PortalHeader, { path: "/" });
    await flushPromises();
    await wrapper.get('[data-testid="nav-group-explore"]').trigger("click");
    await flushPromises();

    const html = wrapper.get('[data-testid="nav-menu-explore"]').text();
    expect(html).toContain(t("nav.mutantLines"));
    expect(html).not.toContain("should not apply");
    wrapper.unmount();
  });
});
