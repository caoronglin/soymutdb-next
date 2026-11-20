import { afterEach, describe, expect, it, vi } from "vitest";
import { http } from "./auth";
import type { ExportQueryFilters } from "./variants";
import {
  createVariantExport,
  getVariantExportDownload,
  getVariantExportManifest,
  getVariantExportStatus,
  searchVariants,
  submitExportQuery,
} from "./variants";

vi.mock("./auth", () => ({ http: { get: vi.fn(), post: vi.fn() } }));

describe("variant client contract", () => {
  afterEach(() => vi.clearAllMocks());

  it("uses exactly the public variant filter vocabulary", async () => {
    vi.mocked(http.get).mockResolvedValue({
      items: [],
      next_cursor: null,
      has_more: false,
      total_count: 0,
    });

    await searchVariants({
      assembly: "Wm82.a4.v1",
      chromosome: "Gm01",
      start: 10,
      end: 20,
      ref: "A",
      alt: "T",
      gene_id: "Glyma.01G000100",
      mutant_line_public_id: "SM7K3ZQ9P2AX",
      variant_type: "SNP",
      consequence: "missense_variant",
      impact: "HIGH",
      min_af: 0.1,
      max_af: 0.9,
      cursor: "opaque-cursor",
      limit: 25,
    });

    expect(http.get).toHaveBeenCalledWith("/variants", {
      params: {
        assembly: "Wm82.a4.v1",
        chromosome: "Gm01",
        start: 10,
        end: 20,
        ref: "A",
        alt: "T",
        gene_id: "Glyma.01G000100",
        mutant_line_public_id: "SM7K3ZQ9P2AX",
        variant_type: "SNP",
        consequence: "missense_variant",
        impact: "HIGH",
        min_af: 0.1,
        max_af: 0.9,
        cursor: "opaque-cursor",
        limit: 25,
      },
    });
  });

  it("reads one export's status and its download link", async () => {
    vi.mocked(http.get).mockResolvedValue({});

    await getVariantExportStatus("export-1");
    await getVariantExportDownload("export-1");

    expect(http.get).toHaveBeenNthCalledWith(1, "/variants/export/export-1");
    expect(http.get).toHaveBeenNthCalledWith(2, "/variants/export/export-1/download");
  });

  it("keeps the submission on the existing endpoint and request shape", async () => {
    vi.mocked(http.post).mockResolvedValue({});
    const body = { format: "tsv", compress: true, filters: { assembly: "v4" } };

    await createVariantExport(body);

    expect(http.post).toHaveBeenCalledWith("/variants/export", { json: body });
  });
});

describe("export provenance and query builder", () => {
  it("fetches the manifest from the owner-scoped export path", async () => {
    vi.mocked(http.get).mockResolvedValue({});
    await getVariantExportManifest("export-1");
    expect(vi.mocked(http.get)).toHaveBeenCalledWith(
      "/variants/export/export-1/manifest",
    );
  });

  it("submits a whitelisted query through the /exports/query endpoint", async () => {
    vi.mocked(http.post).mockResolvedValue({});
    await submitExportQuery({ format: "vcf", filters: { assembly: "Wm82.a4.v1" } });
    expect(vi.mocked(http.post)).toHaveBeenCalledWith(
      "/exports/query",
      expect.objectContaining({
        json: { format: "vcf", filters: { assembly: "Wm82.a4.v1" } },
      }),
    );
  });
  it("forwards every export-query filter key the card can display", async () => {
    vi.mocked(http.post).mockResolvedValue({});
    // The query builder has no second vocabulary: every key the display mirror
    // advertises must survive both the TypeScript type and the request body.
    // Omitting a key here is what let `ref`/`alt` go missing from this type
    // while the API and the card already accepted them.
    const filters: ExportQueryFilters = {
      assembly: "Wm82.a4.v1",
      chromosome: "Gm01",
      start: 10,
      end: 20,
      ref: "A",
      alt: "T",
      gene_id: "Glyma.01G000100",
      variant_type: "SNP",
      consequence: "missense_variant",
      impact: "HIGH",
      min_af: 0.1,
      max_af: 0.9,
      mutant_line_public_id: "SM7K3ZQ9P2AX",
    };

    await submitExportQuery({ format: "vcf", compress: false, filters });

    expect(vi.mocked(http.post)).toHaveBeenCalledWith(
      "/exports/query",
      expect.objectContaining({
        json: { format: "vcf", compress: false, filters },
      }),
    );
  });

  it("does not forward the paging keys an export cannot honour", async () => {
    vi.mocked(http.post).mockResolvedValue({});
    // `limit`/`cursor` exist on the search vocabulary only; the server derives
    // its export whitelist by dropping exactly these two, so a caller that
    // sends them would be refused by `extra="forbid"`.
    const filters = { assembly: "Wm82.a4.v1" } as ExportQueryFilters;

    await submitExportQuery({ filters });

    const body = vi.mocked(http.post).mock.calls.at(-1)?.[1] as {
      json: { filters: Record<string, unknown> };
    };
    expect(Object.keys(body.json.filters)).toEqual(["assembly"]);
    expect(body.json).not.toHaveProperty("filters.limit");
    expect(body.json).not.toHaveProperty("filters.cursor");
  });
});
