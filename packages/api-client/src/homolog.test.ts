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
    const mockResponse = {
      gene_id: "Glyma.01G000100",
      homologs: [{ species: "Arabidopsis", gene_id: "AT1G00010", type: "ortholog", source: "Ensembl" }],
    };
    mockGet.mockResolvedValueOnce(mockResponse);

    const result = await getGeneHomologs("Glyma.01G000100");

    expect(mockGet).toHaveBeenCalledWith("/genes/Glyma.01G000100/homologs");
    expect(result).toEqual(mockResponse);
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
