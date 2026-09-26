// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mountAdminView } from "../test/support";

import {
  createStaticPage,
  deleteStaticPage,
  getStaticPage,
  listStaticPageVersions,
  listStaticPages,
  publishStaticPage,
  unpublishStaticPage,
  updateStaticPage,
  type StaticPageDetail,
} from "@soymutdb/api-client";
import StaticPagesView from "./StaticPagesView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    listStaticPages: vi.fn(),
    getStaticPage: vi.fn(),
    createStaticPage: vi.fn(),
    updateStaticPage: vi.fn(),
    deleteStaticPage: vi.fn(),
    publishStaticPage: vi.fn(),
    unpublishStaticPage: vi.fn(),
    listStaticPageVersions: vi.fn(),
    restoreStaticPageVersion: vi.fn(),
  };
});

const PAGE: StaticPageDetail = {
  id: "7",
  slug: "about-us",
  title_en: "About us",
  title_zh: "关于我们",
  content_en: "<p>Hello</p>",
  content_zh: null,
  status: "draft",
  category: "page",
  summary: "About",
  sort_order: 3,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  author_name: "admin",
  published_at: null,
  current_version: 2,
};

beforeEach(() => {
  vi.mocked(listStaticPages).mockReset().mockResolvedValue({ items: [PAGE], total: 1 });
  vi.mocked(getStaticPage).mockReset().mockResolvedValue(PAGE);
  vi.mocked(listStaticPageVersions).mockReset().mockResolvedValue([]);
  vi.mocked(createStaticPage).mockReset().mockResolvedValue(PAGE);
  vi.mocked(updateStaticPage).mockReset().mockResolvedValue(PAGE);
  vi.mocked(deleteStaticPage).mockReset().mockResolvedValue(undefined);
  vi.mocked(publishStaticPage).mockReset().mockResolvedValue(PAGE);
  vi.mocked(unpublishStaticPage).mockReset().mockResolvedValue(PAGE);
});

describe("StaticPagesView", () => {
  it("lists the server-owned pages including drafts", async () => {
    const { wrapper } = mountAdminView(StaticPagesView, { path: "/content" });
    await flushPromises();

    expect(vi.mocked(listStaticPages)).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, page_size: 20 }),
    );
    expect(wrapper.findAll('[data-testid="page-row"]')).toHaveLength(1);
    expect(wrapper.get('[data-testid="pages-table"]').text()).toContain("About us");
    wrapper.unmount();
  });

  it("filters the list by status server-side", async () => {
    const { wrapper } = mountAdminView(StaticPagesView, { path: "/content" });
    await flushPromises();

    await wrapper.get('[data-testid="pages-status-filter"]').setValue("published");
    await flushPromises();

    expect(vi.mocked(listStaticPages)).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: "published" }),
    );
    wrapper.unmount();
  });

  it("loads the named page into the editor for ?edit=<id>", async () => {
    const { wrapper, router } = mountAdminView(StaticPagesView, { path: "/content" });
    await flushPromises();
    await router.push({ path: "/content", query: { edit: "7" } });
    await flushPromises();

    expect(vi.mocked(getStaticPage)).toHaveBeenCalledWith("7");
    expect(
      (wrapper.get('[data-testid="page-title-en"]').element as HTMLInputElement).value,
    ).toBe("About us");
    expect(
      (wrapper.get('[data-testid="page-slug"]').element as HTMLInputElement).disabled,
    ).toBe(true);
    expect(vi.mocked(listStaticPageVersions)).toHaveBeenCalledWith("7");
    wrapper.unmount();
  });

  it("opens a blank editor for ?new=1 without loading a page", async () => {
    const { wrapper, router } = mountAdminView(StaticPagesView, { path: "/content" });
    await flushPromises();
    await router.push({ path: "/content", query: { new: "1" } });
    await flushPromises();

    expect(vi.mocked(getStaticPage)).not.toHaveBeenCalled();
    expect(
      (wrapper.get('[data-testid="page-title-en"]').element as HTMLInputElement).value,
    ).toBe("");
    expect(
      (wrapper.get('[data-testid="page-slug"]').element as HTMLInputElement).disabled,
    ).toBe(false);
    wrapper.unmount();
  });

  it("creates a page with the typed payload on submit", async () => {
    const { wrapper, router } = mountAdminView(StaticPagesView, { path: "/content" });
    await flushPromises();
    await router.push({ path: "/content", query: { new: "1" } });
    await flushPromises();

    await wrapper.get('[data-testid="page-slug"]').setValue("new-page");
    await wrapper.get('[data-testid="page-title-en"]').setValue("New page");
    await wrapper.get('[data-testid="page-editor"] form').trigger("submit");
    await flushPromises();

    expect(vi.mocked(createStaticPage)).toHaveBeenCalledWith(
      expect.objectContaining({ slug: "new-page", title_en: "New page", status: "draft" }),
    );
    wrapper.unmount();
  });

  it("updates an existing page with a partial payload", async () => {
    const { wrapper, router } = mountAdminView(StaticPagesView, { path: "/content" });
    await flushPromises();
    await router.push({ path: "/content", query: { edit: "7" } });
    await flushPromises();

    await wrapper.get('[data-testid="page-title-en"]').setValue("About us v2");
    await wrapper.get('[data-testid="page-editor"] form').trigger("submit");
    await flushPromises();

    expect(vi.mocked(updateStaticPage)).toHaveBeenCalledWith(
      "7",
      expect.objectContaining({ title_en: "About us v2" }),
    );
    wrapper.unmount();
  });

  it("publishes, unpublishes and deletes through the row actions", async () => {
    const { wrapper } = mountAdminView(StaticPagesView, { path: "/content" });
    await flushPromises();

    await wrapper.get('[data-testid="page-publish-7"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(publishStaticPage)).toHaveBeenCalledWith("7");

    await wrapper.get('[data-testid="page-delete-7"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(deleteStaticPage)).toHaveBeenCalledWith("7");
    wrapper.unmount();
  });

  it("unpublishes a published page", async () => {
    vi.mocked(listStaticPages).mockResolvedValue({
      items: [{ ...PAGE, status: "published" }],
      total: 1,
    });
    const { wrapper } = mountAdminView(StaticPagesView, { path: "/content" });
    await flushPromises();

    await wrapper.get('[data-testid="page-unpublish-7"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(unpublishStaticPage)).toHaveBeenCalledWith("7");
    wrapper.unmount();
  });
});
