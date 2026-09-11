import { beforeEach, describe, expect, it, vi } from "vitest";
import { http } from "./auth";
import {
  listDeletedAdminNews,
  purgeNews,
  restoreNews,
  type DeletedAdminNewsItem,
} from "./admin-news";

vi.mock("./auth", () => ({
  http: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

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

describe("admin news recycle-bin client", () => {
  beforeEach(() => {
    mockHttp.get.mockReset();
    mockHttp.post.mockReset();
    mockHttp.delete.mockReset();
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
});
