// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mountAdminView } from "../test/support";

import {
  getAdminNewsDetail,
  listAdminNews,
  type NewsSummary,
} from "@soymutdb/api-client";
import NewsAdminView from "./NewsAdminView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    listAdminNews: vi.fn(),
    getAdminNewsDetail: vi.fn(),
    createNews: vi.fn(),
    updateNews: vi.fn(),
    deleteNews: vi.fn(),
    restoreNews: vi.fn(),
  };
});

const ARTICLE: NewsSummary = {
  id: "n1",
  slug: "release-notes",
  title_en: "Release notes",
  title_zh: "发布说明",
  status: "draft",
  is_published: false,
  published_at: null,
  created_at: "2026-09-25T00:00:00Z",
  updated_at: "2026-09-25T00:00:00Z",
} as NewsSummary;

beforeEach(() => {
  vi.mocked(listAdminNews).mockReset().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
  vi.mocked(getAdminNewsDetail).mockReset().mockResolvedValue({
    ...ARTICLE,
    content_en: "Body",
    content_zh: null,
  } as never);
});

describe("NewsAdminView legacy deep links", () => {
  it("opens the trash view for ?status=archived and filters server-side", async () => {
    const { wrapper, router } = mountAdminView(NewsAdminView, { path: "/news" });
    await flushPromises();
    await router.push({ path: "/news", query: { status: "archived" } });
    await flushPromises();

    expect(
      (wrapper.get('[data-testid="news-status-filter"]').element as HTMLSelectElement).value,
    ).toBe("archived");
    expect(vi.mocked(listAdminNews)).toHaveBeenCalledWith(
      expect.objectContaining({ status_filter: "archived" }),
    );
    wrapper.unmount();
  });

  it("loads the named article into the editor for ?edit=<id>", async () => {
    const { wrapper, router } = mountAdminView(NewsAdminView, { path: "/news" });
    await flushPromises();
    await router.push({ path: "/news", query: { edit: "n1" } });
    await flushPromises();

    expect(vi.mocked(getAdminNewsDetail)).toHaveBeenCalledWith("n1");
    expect(
      (wrapper.get('[data-testid="news-title-en"]').element as HTMLInputElement).value,
    ).toBe("Release notes");
    wrapper.unmount();
  });

  it("opens a blank editor for ?new=1 without loading an article", async () => {
    const { wrapper, router } = mountAdminView(NewsAdminView, { path: "/news" });
    await flushPromises();
    await router.push({ path: "/news", query: { new: "1" } });
    await flushPromises();

    expect(vi.mocked(getAdminNewsDetail)).not.toHaveBeenCalled();
    expect(
      (wrapper.get('[data-testid="news-title-en"]').element as HTMLInputElement).value,
    ).toBe("");
    expect((wrapper.get('[data-testid="news-status-select"]').element as HTMLSelectElement).value)
      .toBe("draft");
    wrapper.unmount();
  });
});
