/**
 * Tests for expression API functions.
 *
 * Mocks the http client from ./client and verifies correct path/params are
 * passed for each exported function.
 */

import { http } from "./client";
import {
  getGeneExpression,
  getExpressionLibraries,
  searchExpression,
} from "./expression";

vi.mock("./client", () => ({
  http: {
    get: vi.fn(),
  },
}));

const mockGet = vi.mocked(http.get);

// ---------------------------------------------------------------------------
// getGeneExpression
// ---------------------------------------------------------------------------
describe("getGeneExpression", () => {
  it("calls http.get with the gene expression path and params", async () => {
    const mockResponse = { gene_id: "Glyma.01G000100", expressions: [] };
    mockGet.mockResolvedValueOnce(mockResponse);

    const params = { tissue: "root", min_fpkm: 1.0 };
    const result = await getGeneExpression("Glyma.01G000100", params);

    expect(mockGet).toHaveBeenCalledWith("/genes/Glyma.01G000100/expression", {
      params,
    });
    expect(result).toEqual(mockResponse);
  });

  it("works without optional params", async () => {
    mockGet.mockResolvedValueOnce({ gene_id: "G1", expressions: [] });

    await getGeneExpression("G1");

    expect(mockGet).toHaveBeenCalledWith("/genes/G1/expression", {
      params: undefined,
    });
  });
});

// ---------------------------------------------------------------------------
// getExpressionLibraries
// ---------------------------------------------------------------------------
describe("getExpressionLibraries", () => {
  it("calls http.get with /expression/libraries and pagination params", async () => {
    const mockResponse = { items: [], total: 0 };
    mockGet.mockResolvedValueOnce(mockResponse);

    const params = { page: 1, page_size: 20, tissue: "leaf" };
    const result = await getExpressionLibraries(params);

    expect(mockGet).toHaveBeenCalledWith("/expression/libraries", { params });
    expect(result).toEqual(mockResponse);
  });

  it("works without params", async () => {
    mockGet.mockResolvedValueOnce({ items: [], total: 0 });

    await getExpressionLibraries();

    expect(mockGet).toHaveBeenCalledWith("/expression/libraries", {
      params: undefined,
    });
  });
});

// ---------------------------------------------------------------------------
// searchExpression
// ---------------------------------------------------------------------------
describe("searchExpression", () => {
  it("calls http.get with /expression/search and full params", async () => {
    mockGet.mockResolvedValueOnce({ items: [], total: 0 });

    const params = {
      gene_id: "Glyma.01G000100",
      tissue: "root",
      min_fpkm: 0.5,
      page: 1,
      page_size: 50,
    };
    await searchExpression(params);

    expect(mockGet).toHaveBeenCalledWith("/expression/search", { params });
  });

  it("works with minimal params", async () => {
    mockGet.mockResolvedValueOnce({ items: [], total: 0 });

    await searchExpression({ gene_id: "G1" });

    expect(mockGet).toHaveBeenCalledWith("/expression/search", {
      params: { gene_id: "G1" },
    });
  });
});
