import { http } from "./auth";
import {
  adminContentApi,
  createStaticPage,
  deleteStaticPage,
  dryRunStaticPageMigration,
  getStaticPage,
  listStaticPageVersions,
  listStaticPages,
  publishStaticPage,
  restoreStaticPageVersion,
  unpublishStaticPage,
  updateStaticPage,
  type StaticPageDetail,
  type StaticPageListResponse,
  type StaticPageMigrationDryRunReport,
} from "./admin-content";

vi.mock("./auth", () => ({
  http: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockGet = vi.mocked(http.get);
const mockPost = vi.mocked(http.post);
const mockPut = vi.mocked(http.put);
const mockDelete = vi.mocked(http.delete);

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
  mockGet.mockReset();
  mockPost.mockReset();
  mockPut.mockReset();
  mockDelete.mockReset();
});

describe("typed admin content client", () => {
  it("lists pages with server-side filters and pagination", async () => {
    const response: StaticPageListResponse = { items: [PAGE], total: 1 };
    mockGet.mockResolvedValueOnce(response);

    await expect(
      listStaticPages({ status: "draft", category: "page", page: 2, page_size: 50 }),
    ).resolves.toEqual(response);
    expect(mockGet).toHaveBeenCalledWith("/admin/content/pages", {
      params: { status: "draft", category: "page", page: "2", page_size: "50" },
    });
  });

  it("omits empty list parameters", async () => {
    mockGet.mockResolvedValueOnce({ items: [], total: 0 });
    await listStaticPages();
    expect(mockGet).toHaveBeenCalledWith("/admin/content/pages", { params: {} });
  });

  it("reads one page and its version history", async () => {
    mockGet.mockResolvedValueOnce(PAGE);
    await expect(getStaticPage("7")).resolves.toEqual(PAGE);
    expect(mockGet).toHaveBeenCalledWith("/admin/content/pages/7");

    mockGet.mockResolvedValueOnce([
      {
        id: "v1",
        page_id: "7",
        version: 1,
        title_en: "About us",
        title_zh: null,
        content_en: "body",
        content_zh: null,
        summary: null,
        edited_by: null,
        edit_comment: null,
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    await expect(listStaticPageVersions(7)).resolves.toHaveLength(1);
    expect(mockGet).toHaveBeenCalledWith("/admin/content/pages/7/versions");
  });

  it("creates, updates and deletes a page", async () => {
    mockPost.mockResolvedValueOnce(PAGE);
    await expect(
      createStaticPage({ slug: "about-us", title_en: "About us", content_en: "body" }),
    ).resolves.toEqual(PAGE);
    expect(mockPost).toHaveBeenCalledWith("/admin/content/pages", {
      json: { slug: "about-us", title_en: "About us", content_en: "body" },
    });

    mockPut.mockResolvedValueOnce(PAGE);
    await expect(updateStaticPage(7, { title_en: "About" })).resolves.toEqual(PAGE);
    expect(mockPut).toHaveBeenCalledWith("/admin/content/pages/7", {
      json: { title_en: "About" },
    });

    mockDelete.mockResolvedValueOnce(undefined);
    await expect(deleteStaticPage(7)).resolves.toBeUndefined();
    expect(mockDelete).toHaveBeenCalledWith("/admin/content/pages/7");
  });

  it("publishes, unpublishes and restores versions", async () => {
    mockPost.mockResolvedValue(PAGE);
    await publishStaticPage(7);
    expect(mockPost).toHaveBeenCalledWith("/admin/content/pages/7/publish");

    await unpublishStaticPage(7);
    expect(mockPost).toHaveBeenCalledWith("/admin/content/pages/7/unpublish");

    await restoreStaticPageVersion(7, 1);
    expect(mockPost).toHaveBeenCalledWith("/admin/content/pages/7/versions/1/restore");
  });

  it("requests the read-only migration preview without a body by default", async () => {
    const report: StaticPageMigrationDryRunReport = {
      dry_run: true,
      created: 0,
      skipped: 0,
      invalid: 0,
      items: [],
    };
    mockPost.mockResolvedValueOnce(report);
    await expect(dryRunStaticPageMigration()).resolves.toEqual(report);
    expect(mockPost).toHaveBeenCalledWith(
      "/admin/content/pages/migrate-to-page-builder/dry-run",
      { json: {} },
    );
  });

  it("exposes the same operations through the grouped namespace", () => {
    expect(adminContentApi.list).toBe(listStaticPages);
    expect(adminContentApi.get).toBe(getStaticPage);
    expect(adminContentApi.create).toBe(createStaticPage);
    expect(adminContentApi.update).toBe(updateStaticPage);
    expect(adminContentApi.remove).toBe(deleteStaticPage);
    expect(adminContentApi.publish).toBe(publishStaticPage);
    expect(adminContentApi.unpublish).toBe(unpublishStaticPage);
    expect(adminContentApi.versions).toBe(listStaticPageVersions);
    expect(adminContentApi.restore).toBe(restoreStaticPageVersion);
    expect(adminContentApi.dryRunMigration).toBe(dryRunStaticPageMigration);
  });
});
