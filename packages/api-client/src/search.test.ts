import { afterEach, describe, expect, it, vi } from "vitest";
import { http } from "./auth";
import { globalSearch, internalSearch, type SearchResult } from "./search";

vi.mock("./auth", () => ({ http: { get: vi.fn() } }));

describe("search client contract", () => {
  afterEach(() => vi.clearAllMocks());

  it("serializes types/cursor/limit/assembly and never page_size", async () => {
    vi.mocked(http.get).mockResolvedValueOnce({});
    await globalSearch({
      q: "Glyma",
      types: ["gene"],
      cursor: "c1",
      limit: 20,
      assembly_id: 11,
    });
    expect(http.get).toHaveBeenCalledWith("/search", {
      params: {
        types: ["gene"],
        cursor: "c1",
        limit: 20,
        assembly_id: 11,
        query: "Glyma",
      },
    });
    expect(vi.mocked(http.get).mock.calls[0][1]?.params).not.toHaveProperty("page_size");
  });

  // OPT-05: the authorized internal endpoint is a separate route returning BOTH
  // identities. The client must use the backend's `query` alias (not `q`) and go
  // through the coordinated `http` wrapper so the Authorization header and the
  // release pin are attached by the transport, exactly like /search.
  it("internalSearch hits /search/internal with the query alias and limit", async () => {
    vi.mocked(http.get).mockResolvedValueOnce({});
    await internalSearch("node-42", { limit: 5 });
    expect(http.get).toHaveBeenCalledWith("/search/internal", {
      params: { query: "node-42", limit: 5 },
    });
  });

  it("internalSearch defaults the limit when no options are supplied", async () => {
    vi.mocked(http.get).mockResolvedValueOnce({});
    await internalSearch("SM7QF3Z");
    expect(http.get).toHaveBeenCalledWith("/search/internal", {
      params: { query: "SM7QF3Z", limit: undefined },
    });
  });

  // OPT-06: the new fields are optional on the handwritten type, so a payload
  // from a backend that has not shipped the crosswalk yet still type-checks.
  it("SearchResult accepts optional match_type/cross_version and a bare shape", () => {
    const bare: SearchResult = { type: "gene", id: "g1" };
    const rich: SearchResult = {
      type: "gene",
      id: "g1",
      match_type: "cross-version",
      cross_version: [
        {
          gene_accession: "g2",
          relation_type: "alias",
          provenance_source: "gene_crosswalks",
        },
      ],
    };
    expect(bare.match_type).toBeUndefined();
    expect(rich.match_type).toBe("cross-version");
    expect(rich.cross_version).toHaveLength(1);
  });
});
