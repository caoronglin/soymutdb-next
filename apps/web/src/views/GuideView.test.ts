// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";

import { getSiteContent, http } from "@soymutdb/api-client";
import { mountPortalView } from "../test/mount-portal-view";
import { setLanguage, t } from "../lib/i18n";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GuideView from "./GuideView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getSiteContent: vi.fn() };
});

const mockedSiteContent = vi.mocked(getSiteContent);
const httpGet = vi.spyOn(http, "get");

const PAGE = {
  id: "page-1",
  slug: "ncbi-database-guide",
  title_en: "NCBI Database Guide",
  title_zh: null,
  content_en: "## Retrieval\nHow to retrieve records.",
  content_zh: null,
};

beforeEach(() => {
  setLanguage("en");
  mockedSiteContent.mockReset().mockResolvedValue({});
  httpGet.mockReset().mockResolvedValue(PAGE as never);
});

async function mountGuide() {
  const result = mountPortalView(GuideView, { path: "/guide" });
  await flushPromises();
  await flushPromises();
  return result;
}

describe("GuideView editable content", () => {
  it("keeps the API page title in the heading and the nav label as the eyebrow", async () => {
    const { wrapper } = await mountGuide();

    // React parity: `<h1>{title}</h1>` is the API page title, while
    // `get("nav.guide", …)` renders as the small badge above it.
    expect(wrapper.get("h1").text()).toBe("NCBI Database Guide");
    expect(wrapper.get("p.eyebrow").text()).toBe(t("nav.guide"));
    wrapper.unmount();
  });

  it("renders the operator override in the eyebrow, not in the heading", async () => {
    mockedSiteContent.mockResolvedValue({ "nav.guide": "运营指南" });

    const { wrapper } = await mountGuide();

    expect(wrapper.get("p.eyebrow").text()).toBe("运营指南");
    expect(wrapper.get("h1").text()).toBe("NCBI Database Guide");
    wrapper.unmount();
  });
});
