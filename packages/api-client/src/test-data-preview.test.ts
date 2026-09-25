import { afterEach, describe, expect, it, vi } from "vitest";
import { http } from "./auth";
import {
  getTestDataPreviewMeta,
  searchTestDataPreviewGenes,
  searchTestDataPreviewMutationSites,
} from "./test-data-preview";

vi.mock("./auth", () => ({ http: { get: vi.fn() } }));

describe("local test-data preview client contract", () => {
  afterEach(() => vi.clearAllMocks());

  it("reads the preview manifest from its isolated endpoint", async () => {
    vi.mocked(http.get).mockResolvedValue({
      preview: true,
      publication_status: "unpublished",
      coordinate_system: "1-based-inclusive",
      dataset: { key: "03_soymut-a6-test", source_file: "test.tsv", source_sha256: "a".repeat(64), row_count: 0 },
      assembly: { name: "Gmax_880_v6.0", version: "v6.0", species: "Glycine max", status: "unpublished" },
      annotation_version: "Wm82.a6.v1",
      chromosomes: [],
    });

    await getTestDataPreviewMeta();

    expect(http.get).toHaveBeenCalledWith("/preview/test-data/meta");
  });

  it("rejects a response that omits the unpublished preview marker", async () => {
    vi.mocked(http.get).mockResolvedValue({
      preview: false,
      publication_status: "published",
    });

    await expect(getTestDataPreviewMeta()).rejects.toThrow(/unpublished-data marker/);
  });

  it("sends exact gene IDs only to the preview gene endpoint", async () => {
    vi.mocked(http.get).mockResolvedValue({
      preview: true,
      publication_status: "unpublished",
      assembly: { name: "Gmax_880_v6.0", version: "v6.0", species: "Glycine max", status: "unpublished" },
      annotation_version: "Wm82.a6.v1",
      items: [],
      total: 0,
      limit: 100,
    });
    const params = { gene_id: "Glyma.01G000100.Wm82.a6.v1", limit: 100 };

    await searchTestDataPreviewGenes(params);

    expect(http.get).toHaveBeenCalledWith("/preview/test-data/genes", { params });
  });

  it("keeps physical test-site fields in the dedicated non-variant endpoint", async () => {
    vi.mocked(http.get).mockResolvedValue({
      preview: true,
      publication_status: "unpublished",
      coordinate_system: "1-based-inclusive",
      assembly: { name: "Gmax_880_v6.0", version: "v6.0", species: "Glycine max", status: "unpublished" },
      annotation_version: "Wm82.a6.v1",
      items: [],
      total: 0,
      limit: 1000,
    });
    const params = { chromosome: "Gm01", start: 98256, end: 98256, limit: 1000 };

    await searchTestDataPreviewMutationSites(params);

    expect(http.get).toHaveBeenCalledWith("/preview/test-data/mutation-sites", { params });
  });
});
