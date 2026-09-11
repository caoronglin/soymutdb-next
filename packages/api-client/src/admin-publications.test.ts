import { beforeEach, describe, expect, it, vi } from "vitest";
import { http } from "./auth";
import {
  createAdminPublication,
  deleteAdminPublication,
  listAdminPublications,
  updateAdminPublication,
} from "./admin-publications";

vi.mock("./auth", () => ({
  http: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockHttp = vi.mocked(http);

describe("admin publications client", () => {
  beforeEach(() => {
    mockHttp.get.mockReset();
    mockHttp.post.mockReset();
    mockHttp.put.mockReset();
    mockHttp.delete.mockReset();
  });

  it("uses the coordinated auth transport for every admin publication operation", async () => {
    mockHttp.get.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
    mockHttp.post.mockResolvedValue({ id: 1, title: "Created" } as never);
    mockHttp.put.mockResolvedValue({ id: 1, title: "Updated" } as never);
    mockHttp.delete.mockResolvedValue(undefined as never);

    await listAdminPublications({ page: 2, page_size: 10, search: "soy", is_featured: true });
    await createAdminPublication({ title: "Created", authors: "Author" });
    await updateAdminPublication(1, { title: "Updated" });
    await deleteAdminPublication(1);

    expect(mockHttp.get).toHaveBeenCalledWith("/admin/publications", {
      params: { page: 2, page_size: 10, search: "soy", is_featured: true },
    });
    expect(mockHttp.post).toHaveBeenCalledWith("/admin/publications", {
      json: { title: "Created", authors: "Author" },
    });
    expect(mockHttp.put).toHaveBeenCalledWith("/admin/publications/1", {
      json: { title: "Updated" },
    });
    expect(mockHttp.delete).toHaveBeenCalledWith("/admin/publications/1");
  });
});
