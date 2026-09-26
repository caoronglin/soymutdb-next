// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mountAdminView } from "../test/support";

import {
  getAdminNewsDetail,
  listAdminNews,
  listDeletedAdminNews,
  purgeNews,
  restoreNews,
  type DeletedAdminNewsItem,
  type NewsSummary,
} from "@soymutdb/api-client";
import NewsAdminView from "./NewsAdminView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    listAdminNews: vi.fn(),
    listDeletedAdminNews: vi.fn(),
    getAdminNewsDetail: vi.fn(),
    createNews: vi.fn(),
    updateNews: vi.fn(),
    deleteNews: vi.fn(),
    restoreNews: vi.fn(),
    purgeNews: vi.fn(),
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

const DELETED: DeletedAdminNewsItem = {
  id: 7,
  title_en: "Deleted article",
  title_zh: "已删除文章",
  slug: "deleted-article",
  category: null,
  status: "draft",
  published_at: null,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
  deleted_at: "2026-09-02T00:00:00Z",
};

beforeEach(() => {
  vi.mocked(listAdminNews).mockReset().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
  vi.mocked(listDeletedAdminNews)
    .mockReset()
    .mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
  vi.mocked(getAdminNewsDetail).mockReset().mockResolvedValue({
    ...ARTICLE,
    content_en: "Body",
    content_zh: null,
  } as never);
  vi.mocked(restoreNews).mockReset().mockResolvedValue({} as never);
  vi.mocked(purgeNews).mockReset().mockResolvedValue(undefined as never);
});

describe("NewsAdminView legacy deep links", () => {
  it("filters to archived articles for ?status=archived", async () => {
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

describe("NewsAdminView recycle bin", () => {
  it("lists soft-deleted articles from the trash endpoint and restores one", async () => {
    vi.mocked(listDeletedAdminNews).mockResolvedValue({
      items: [DELETED],
      total: 1,
      page: 1,
      page_size: 20,
    });
    const { wrapper, router } = mountAdminView(NewsAdminView, { path: "/news" });
    await flushPromises();
    await router.push({ path: "/news", query: { status: "trash" } });
    await flushPromises();

    expect(
      (wrapper.get('[data-testid="news-status-filter"]').element as HTMLSelectElement).value,
    ).toBe("trash");
    expect(vi.mocked(listDeletedAdminNews)).toHaveBeenCalledWith({ page: 1, page_size: 20 });
    expect(wrapper.find('[data-testid="news-trash-table"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="news-table"]').exists()).toBe(false);

    await wrapper.get('[data-testid="news-restore-7"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(restoreNews)).toHaveBeenCalledWith("7");
    wrapper.unmount();
  });

  it("requires an explicit second click before permanently purging", async () => {
    vi.mocked(listDeletedAdminNews).mockResolvedValue({
      items: [DELETED],
      total: 1,
      page: 1,
      page_size: 20,
    });
    const { wrapper, router } = mountAdminView(NewsAdminView, { path: "/news" });
    await flushPromises();
    await router.push({ path: "/news", query: { status: "trash" } });
    await flushPromises();

    await wrapper.get('[data-testid="news-purge-7"]').trigger("click");
    expect(vi.mocked(purgeNews)).not.toHaveBeenCalled();

    await wrapper.get('[data-testid="news-purge-confirm-7"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(purgeNews)).toHaveBeenCalledWith("7");
    wrapper.unmount();
  });

  it("shows the empty state when the recycle bin is empty", async () => {
    const { wrapper, router } = mountAdminView(NewsAdminView, { path: "/news" });
    await flushPromises();
    await router.push({ path: "/news", query: { status: "trash" } });
    await flushPromises();

    expect(wrapper.find('[data-testid="news-trash-empty"]').exists()).toBe(true);
    wrapper.unmount();
  });
});

describe("NewsAdminView bilingual preview", () => {
  it("renders sanitised Markdown for both languages as the editor is typed", async () => {
    const { wrapper } = mountAdminView(NewsAdminView, { path: "/news" });
    await flushPromises();

    await wrapper.get('[data-testid="news-body"]').setValue(
      "# Heading\n\n**bold** and <script>alert(1)</script>",
    );
    await wrapper.get('[data-testid="news-body-zh"]').setValue("## 标题\n\n*斜体*");
    await flushPromises();

    const en = wrapper.get('[data-testid="news-preview-en"]').html();
    expect(en).toContain("<h1>Heading</h1>");
    expect(en).toContain("<strong>bold</strong>");
    expect(en).toContain("&lt;script&gt;");
    expect(en).not.toContain("<script>alert(1)</script>");

    const zh = wrapper.get('[data-testid="news-preview-zh"]').html();
    expect(zh).toContain("<h2>标题</h2>");
    expect(zh).toContain("<em>斜体</em>");
    wrapper.unmount();
  });
});
