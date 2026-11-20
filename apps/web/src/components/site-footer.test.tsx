import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SiteFooter as FooterData } from "@soymutdb/api-client";
import { SiteFooter } from "./site-footer";
import { SITE_VARIANT } from "../lib/site-variant";

const runtime = vi.hoisted(() => ({ language: "en", getFooter: vi.fn() }));
vi.mock("@soymutdb/api-client", () => ({ getSiteFooter: runtime.getFooter }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({
  i18n: { language: runtime.language },
  t: (key: string, options?: { year?: number }) => ({ "footer.label": "Footer", "footer.address": "Local address", "footer.copyright": `© ${options?.year} SoyMutDB` })[key] ?? key,
}) }));

const data: FooterData = {
  contact_person: "联系人： Legacy person", contact_phone: "电话: 12345678", contact_email: "电子邮件： legacy@example.org", address: "地址: Legacy address", copyright: "Legacy copyright",
  contact_person_en: "English person", contact_person_zh: "中文联系人", contact_phone_value: "+86 (25) 1234-5678", contact_email_value: "contact@example.org",
  address_en: "English address", address_zh: "中文地址", copyright_en: "English {{year}}", copyright_zh: "中文 {{year}}",
  navigation: [{ id: "resources", title_en: "Resources", title_zh: "资源", enabled: true, order: 0, links: [
    { id: "genes", label_en: "Genes", label_zh: "基因", target: "internal", href: "/genes", enabled: true, order: 0 },
    { id: "external", label_en: "Reference", label_zh: "参考", target: "external", href: "https://example.org/", enabled: true, order: 1 },
    { id: "disabled", label_en: "Disabled", label_zh: "关闭", target: "internal", href: "/disabled", enabled: false, order: 2 },
  ] }],
};

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><SiteFooter /></QueryClientProvider>);
}

beforeEach(() => {
  runtime.language = "en";
  runtime.getFooter.mockReset().mockResolvedValue(structuredClone(data));
});
afterEach(cleanup);

describe("public footer contract", () => {
  it("renders bilingual API values and safe contacts for the explicit variant", async () => {
    const view = mount();
    expect(await screen.findByText(/English person/)).toBeTruthy();
    expect(runtime.getFooter).toHaveBeenCalledWith(SITE_VARIANT);
    expect(screen.getByRole("link", { name: "+86 (25) 1234-5678" }).getAttribute("href")).toBe("tel:+862512345678");
    expect(screen.getByRole("link", { name: "contact@example.org" }).getAttribute("href")).toBe("mailto:contact@example.org");
    expect(screen.queryByText("Resources")).toBeNull();
    runtime.language = "zh-CN";
    view.rerender(<QueryClientProvider client={new QueryClient()}><SiteFooter /></QueryClientProvider>);
    expect(await screen.findByText(/中文联系人/)).toBeTruthy();
    expect(screen.queryByText("English address")).toBeNull();
  });

  it("suppresses unsafe contact links without interpreting HTML", async () => {
    const poisoned = structuredClone(data);
    poisoned.contact_person_en = "<img src=x onerror=alert(1)>";
    poisoned.contact_phone_value = "javascript:alert(1)";
    poisoned.contact_email_value = "user@example.org?subject=injected";
    runtime.getFooter.mockResolvedValue(poisoned);
    mount();
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeTruthy();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(document.querySelector("footer img")).toBeNull();
  });

  it("falls back independently to legacy values and local copy on request failure", async () => {
    runtime.getFooter.mockResolvedValue({ ...data, address_en: null, copyright_en: null, contact_person_en: null, navigation: [] });
    const view = mount();
    expect(await screen.findByText("Legacy address")).toBeTruthy();
    expect(screen.getByText(/Legacy person/)).toBeTruthy();
    expect(screen.getByText("Legacy copyright")).toBeTruthy();
    view.unmount();
    runtime.getFooter.mockRejectedValue(new Error("private transport diagnostic"));
    mount();
    await waitFor(() => expect(runtime.getFooter).toHaveBeenCalledTimes(2));
    // No address was published, so no address line may appear -- and the
    // transport error must never surface as copy.
    expect(screen.queryByText("Local address")).toBeNull();
    expect(screen.queryByText("private transport diagnostic")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
