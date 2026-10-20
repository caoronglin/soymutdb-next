import { http } from "./auth";
import * as releases from "./releases";
import {
  getActiveRelease,
  getAdminRelease,
  getAdminReleases,
  getRelease,
  getReleases,
} from "./releases";

vi.mock("./auth", () => ({
  http: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockGet = vi.mocked(http.get);
const mockPost = vi.mocked(http.post);
const mockPatch = vi.mocked(http.patch);
const mockDelete = vi.mocked(http.delete);

const PUBLISHED = {
  id: "7",
  version: "v5.0.0",
  name: "Glycine max v5",
  description: "Soybean reference 5",
  variant_count: 1234,
  gene_count: 56,
  mutant_line_count: 7,
  status: "published",
  published_at: "2026-10-02T08:30:00Z",
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-10-02T08:30:00Z",
} as const;

const DRAFT = { ...PUBLISHED, id: "3", status: "draft", published_at: null };

describe("releases client", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    mockPatch.mockReset();
    mockDelete.mockReset();
  });

  it("reads the active release pointer", async () => {
    const active = {
      release_id: "7",
      version: "v5.0.0",
      published_at: "2026-10-02T08:30:00Z",
    };
    mockGet.mockResolvedValueOnce(active);

    await expect(getActiveRelease()).resolves.toEqual(active);
    expect(mockGet).toHaveBeenCalledWith("/releases/active");
  });

  it("lists public releases without a variant override", async () => {
    mockGet.mockResolvedValueOnce([PUBLISHED]);

    await expect(getReleases({ status: "published" })).resolves.toEqual([
      PUBLISHED,
    ]);
    expect(mockGet).toHaveBeenCalledWith("/releases", {
      params: { status: "published" },
    });
  });

  it("reads one release", async () => {
    mockGet.mockResolvedValueOnce(PUBLISHED);

    await expect(getRelease("7")).resolves.toEqual(PUBLISHED);
    expect(mockGet).toHaveBeenCalledWith("/releases/7");
  });

  // The admin reads go through the public "/releases" route with the internal
  // variant, which is what the backend actually serves. That query parameter
  // is what makes the API require an administrator and answer
  // "private, no-store" (see _read_scope in apps/api/app/api/v1/releases.py),
  // so the private-cache contract depends on it being sent.
  it("reads admin releases through the internal variant", async () => {
    mockGet.mockResolvedValueOnce([PUBLISHED, DRAFT]);

    await expect(getAdminReleases()).resolves.toEqual([PUBLISHED, DRAFT]);
    expect(mockGet).toHaveBeenCalledWith("/releases", {
      params: { variant: "internal" },
    });

    mockGet.mockResolvedValueOnce([DRAFT]);
    await getAdminReleases({ status: "draft" });
    expect(mockGet).toHaveBeenLastCalledWith("/releases", {
      params: { status: "draft", variant: "internal" },
    });
  });

  it("reads a single admin release through the internal variant", async () => {
    mockGet.mockResolvedValueOnce(DRAFT);

    await expect(getAdminRelease("3")).resolves.toEqual(DRAFT);
    expect(mockGet).toHaveBeenCalledWith("/releases/3", {
      params: { variant: "internal" },
    });
  });

  // No router serves "/releases/{id}/provenance"; it was allowlisted debt.
  it("does not expose the unserved provenance route", () => {
    expect(releases).not.toHaveProperty("getReleaseProvenance");
  });

  it("never issues a mutating request", async () => {
    mockGet.mockResolvedValue([]);

    await getActiveRelease();
    await getReleases();
    await getRelease("7");
    await getAdminReleases();
    await getAdminRelease("7");

    expect(mockPost).not.toHaveBeenCalled();
    expect(mockPatch).not.toHaveBeenCalled();
    expect(mockDelete).not.toHaveBeenCalled();
  });
});
