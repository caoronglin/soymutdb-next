/**
 * Tests for public tools API functions (seqfetch / enrichment / exppattern).
 *
 * Mocks `globalThis.fetch` and verifies URL, method, JSON body, response
 * parsing, and that NO Authorization header is attached (public endpoints).
 */

import {
  seqFetchGenes,
  seqFetchRegion,
  runEnrichment,
  runExpPattern,
} from "./tools";

const API_BASE = "/api/v1";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function lastFetchCall(): [string, RequestInit] {
  const calls = vi.mocked(fetch).mock.calls;
  return calls[calls.length - 1] as unknown as [string, RequestInit];
}

function assertNoAuth(init: RequestInit): void {
  expect(new Headers(init.headers).get("Authorization")).toBeNull();
}

describe("tools (public, no auth)", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({}));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // -------------------------------------------------------------------------
  // seqFetchGenes
  // -------------------------------------------------------------------------
  describe("seqFetchGenes", () => {
    it("POSTs { genes } to /tools/seqfetch and parses the response", async () => {
      const response = {
        format: "fasta",
        sequence: ">Glyma.01G000100\nATGC\n",
        count: 1,
        truncated: false,
        missing: ["Glyma.99G999999"],
        download_url: null,
        expires_in: null,
      };
      vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(response));

      const result = await seqFetchGenes(["Glyma.01G000100"]);

      const [url, init] = lastFetchCall();
      expect(url).toBe(`${API_BASE}/tools/seqfetch`);
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({
        genes: ["Glyma.01G000100"],
      });
      assertNoAuth(init);
      expect(result).toEqual(response);
    });
  });

  // -------------------------------------------------------------------------
  // seqFetchRegion
  // -------------------------------------------------------------------------
  describe("seqFetchRegion", () => {
    it("POSTs { assembly, region } to /tools/seqfetch", async () => {
      const response = {
        format: "fasta",
        sequence: ">chr1:1000-2000\nACGT\n",
        count: 1,
        truncated: false,
        missing: [],
        download_url: null,
        expires_in: null,
      };
      vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(response));

      const result = await seqFetchRegion("GmWm82.a2.v1", "chr1:1000-2000");

      const [url, init] = lastFetchCall();
      expect(url).toBe(`${API_BASE}/tools/seqfetch`);
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({
        assembly: "GmWm82.a2.v1",
        region: "chr1:1000-2000",
      });
      assertNoAuth(init);
      expect(result).toEqual(response);
    });
  });

  // -------------------------------------------------------------------------
  // runEnrichment
  // -------------------------------------------------------------------------
  describe("runEnrichment", () => {
    it("POSTs the enrichment request to /tools/enrichment and parses terms", async () => {
      const response = {
        ontology: "go" as const,
        input_genes: 2,
        background_genes: 100,
        terms: [
          {
            id: "GO:0008150",
            name: "biological_process",
            p_value: 0.001,
            q_value: 0.01,
            gene_count: 2,
            genes: ["Glyma.01G000100"],
          },
        ],
        message: null,
      };
      vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(response));

      const result = await runEnrichment({
        genes: ["Glyma.01G000100", "Glyma.01G000200"],
        mode: "ora",
        ontology: "go",
        p_threshold: 0.05,
        max_terms: 20,
        min_genes: 5,
      });

      const [url, init] = lastFetchCall();
      expect(url).toBe(`${API_BASE}/tools/enrichment`);
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({
        genes: ["Glyma.01G000100", "Glyma.01G000200"],
        mode: "ora",
        ontology: "go",
        p_threshold: 0.05,
        max_terms: 20,
        min_genes: 5,
      });
      assertNoAuth(init);
      expect(result).toEqual(response);
    });
  });

  // -------------------------------------------------------------------------
  // runExpPattern
  // -------------------------------------------------------------------------
  describe("runExpPattern", () => {
    it("POSTs the exppattern request to /tools/exppattern and parses the matrix", async () => {
      const response = {
        genes: ["Glyma.01G000100"],
        conditions: ["root"],
        matrix: [[1.5]],
        row_order: [0],
        clustering: "input",
        value_range: [1.5, 1.5],
        missing_genes: [],
        scale: "zscore",
      };
      vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(response));

      const result = await runExpPattern({
        genes: ["Glyma.01G000100"],
        conditions: ["root"],
        cluster_rows: false,
        scale: "zscore",
      });

      const [url, init] = lastFetchCall();
      expect(url).toBe(`${API_BASE}/tools/exppattern`);
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({
        genes: ["Glyma.01G000100"],
        conditions: ["root"],
        cluster_rows: false,
        scale: "zscore",
      });
      assertNoAuth(init);
      expect(result).toEqual(response);
    });
  });
});
