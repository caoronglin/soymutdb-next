import { beforeEach, describe, expect, it, vi } from "vitest";
import { http } from "./auth";
import {
  createNews,
  deleteNews,
  getAdminNewsDetail,
  listAdminNews,
  listDeletedAdminNews,
  purgeNews,
  reorderNews,
  restoreNews,
  updateNews,
  type DeletedAdminNewsItem,
} from "./admin-news";
import { getNewsBySlug } from "./news";

vi.mock("./auth", () => ({
  http: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("./news", () => ({ getNewsBySlug: vi.fn() }));

const mockHttp = vi.mocked(http);

const deletedItem: DeletedAdminNewsItem = {
  id: 7,
  title_en: "Deleted article",
  title_zh: null,
  slug: "deleted-article",
  category: "news",
  status: "draft",
  published_at: null,
  created_at: "2026-08-31T00:00:00Z",
  updated_at: "2026-08-31T00:00:00Z",
  deleted_at: "2026-08-31T00:00:00Z",
};

describe("admin news client", () => {
  beforeEach(() => {
    mockHttp.get.mockReset();
    mockHttp.post.mockReset();
    mockHttp.put.mockReset();
    mockHttp.patch.mockReset();
    mockHttp.delete.mockReset();
    vi.mocked(getNewsBySlug).mockReset();
  });

  it("lists every status with the server-side filters encoded", async () => {
    mockHttp.get.mockResolvedValue({ items: [], total: 0, page: 2, page_size: 10 });
    await listAdminNews({
      status_filter: "draft",
      category: "news",
      search: "soy",
      page: 2,
      page_size: 10,
    });
    expect(mockHttp.get).toHaveBeenCalledWith("/admin/news", {
      params: {
        status_filter: "draft",
        category: "news",
        search: "soy",
        page: "2",
        page_size: "10",
      },
    });
  });

  it("uses exact authenticated transport methods and recycle-bin endpoints", async () => {
    mockHttp.get.mockResolvedValue({ items: [deletedItem], total: 1, page: 2, page_size: 10 });
    mockHttp.post.mockResolvedValue({ id: 7 } as never);
    mockHttp.delete.mockResolvedValue(undefined as never);

    await listDeletedAdminNews({ page: 2, page_size: 10 });
    await restoreNews(7);
    await purgeNews(7);

    expect(mockHttp.get).toHaveBeenCalledWith("/admin/news/deleted", {
      params: { page: "2", page_size: "10" },
    });
    expect(mockHttp.post).toHaveBeenCalledWith("/admin/news/7/restore");
    expect(mockHttp.delete).toHaveBeenCalledWith("/admin/news/7/purge");
  });

  it("creates, updates and soft-deletes through the admin CRUD routes", async () => {
    mockHttp.post.mockResolvedValue({ id: 7 } as never);
    mockHttp.put.mockResolvedValue({ id: 7 } as never);
    mockHttp.delete.mockResolvedValue(undefined as never);

    await createNews({ title_en: "T", content_en: "B", slug: "t" });
    await updateNews(7, { title_en: "T2", content_zh: "中文" });
    await deleteNews(7);

    expect(mockHttp.post).toHaveBeenCalledWith("/admin/news", {
      json: { title_en: "T", content_en: "B", slug: "t" },
    });
    expect(mockHttp.put).toHaveBeenCalledWith("/admin/news/7", {
      json: { title_en: "T2", content_zh: "中文" },
    });
    expect(mockHttp.delete).toHaveBeenCalledWith("/admin/news/7");
  });

  it("mints a preview token and reads the detail by its slug", async () => {
    mockHttp.get.mockResolvedValueOnce({
      preview: "tok",
      exp: 999,
      url: "/api/v1/news/my-slug?preview=tok&exp=999",
    });
    vi.mocked(getNewsBySlug).mockResolvedValueOnce({ slug: "my-slug" } as never);

    await expect(getAdminNewsDetail(7)).resolves.toEqual({ slug: "my-slug" });
    expect(mockHttp.get).toHaveBeenCalledWith("/admin/news/7/preview-token");
    expect(getNewsBySlug).toHaveBeenCalledWith("my-slug", "tok", 999);
  });

  it("rejects a preview token whose url carries no slug", async () => {
    mockHttp.get.mockResolvedValueOnce({ preview: "tok", exp: 999, url: "/api/v1/news" });
    await expect(getAdminNewsDetail(7)).rejects.toThrow(/Cannot derive slug/);
  });

  it("applies a drag order through PATCH /admin/news/reorder", async () => {
    mockHttp.patch.mockResolvedValue({ updated: 2 });
    await reorderNews([
      { id: 1, featured_sort: 0 },
      { id: 2, featured_sort: 1 },
    ]);
    expect(mockHttp.patch).toHaveBeenCalledWith("/admin/news/reorder", {
      json: {
        items: [
          { id: 1, featured_sort: 0 },
          { id: 2, featured_sort: 1 },
        ],
      },
    });
  });
});
