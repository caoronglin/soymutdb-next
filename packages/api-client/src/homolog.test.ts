/**
 * Tests for homolog API functions.
 *
 * Mocks the http client and verifies correct path/params for each function.
 */

import { http } from "./auth";
import { getGeneHomologs, searchHomologs } from "./homolog";

vi.mock("./auth", () => ({
  http: {
    get: vi.fn(),
  },
}));

const mockGet = vi.mocked(http.get);

// ---------------------------------------------------------------------------
// getGeneHomologs
// ---------------------------------------------------------------------------
describe("getGeneHomologs", () => {
  it("calls http.get with the correct per-gene path", async () => {
    const apiResponse = {
      gene_id: "Glyma.01G000100",
      homologs: [{
        homolog_species: "Arabidopsis",
        homolog_gene_id: "AT1G00010",
        homolog_type: "ortholog",
        source: "Ensembl",
      }],
      next_cursor: null,
      has_more: false,
    };
    mockGet.mockResolvedValueOnce(apiResponse);

    const result = await getGeneHomologs("Glyma.01G000100");

    // No assembly scope → params stay undefined; assembly is forwarded only
    // when provided (see the test below).
    expect(mockGet).toHaveBeenCalledWith("/homologs/genes/Glyma.01G000100/homologs", {
      params: undefined,
    });
    expect(result).toEqual({
      gene_id: "Glyma.01G000100",
      homologs: [{ species: "Arabidopsis", gene_id: "AT1G00010", type: "ortholog", source: "Ensembl" }],
      next_cursor: null,
      has_more: false,
    });
  });

  it("forwards the assembly scope when provided", async () => {
    mockGet.mockResolvedValueOnce({
      gene_id: "Glyma.01G000100",
      homologs: [],
      next_cursor: null,
      has_more: false,
    });

    await getGeneHomologs("Glyma.01G000100", { assembly_id: "4", cursor: "11", limit: 20 });

    expect(mockGet).toHaveBeenCalledWith("/homologs/genes/Glyma.01G000100/homologs", {
      params: { assembly_id: "4", cursor: "11", limit: 20 },
    });
  });
});

// ---------------------------------------------------------------------------
// searchHomologs
// ---------------------------------------------------------------------------
describe("searchHomologs", () => {
  it("calls http.get with /homologs/search and params", async () => {
    mockGet.mockResolvedValueOnce({ items: [], total: 0 });

    const params = { gene_id: "Glyma.01G000100", species: "Arabidopsis", page: 1, page_size: 20 };
    await searchHomologs(params);

    expect(mockGet).toHaveBeenCalledWith("/homologs/search", { params });
  });

  it("works with minimal gene_id filter", async () => {
    mockGet.mockResolvedValueOnce({ items: [], total: 0 });

    await searchHomologs({ gene_id: "G1" });

    expect(mockGet).toHaveBeenCalledWith("/homologs/search", {
      params: { gene_id: "G1" },
    });
  });
});
