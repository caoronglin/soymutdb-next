import { getGene, searchGenes } from "./genes";
import { afterEach, describe, expect, it, vi } from "vitest";

describe("gene client contract", () => {
  afterEach(() => vi.restoreAllMocks());

  it("maps the portal query and page parameters to the API contract", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [],
          page: 2,
          page_size: 20,
          total: 0,
          total_pages: 0,
          next_cursor: null,
          has_more: false,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    await searchGenes({ q: "Glyma.01G000100", cursor: "c1", limit: 20 });

    const [url] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "http://localhost");
    expect(parsed.searchParams.get("search")).toBe("Glyma.01G000100");
    expect(parsed.searchParams.get("cursor")).toBe("c1");
    expect(parsed.searchParams.get("limit")).toBe("20");
    expect(parsed.searchParams.has("q")).toBe(false);
  });
});

describe("gene detail sequence/evidence contract", () => {
  afterEach(() => vi.restoreAllMocks());

  it("keeps an unavailable molecule unavailable instead of defaulting it to a sequence", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          gene_id: "Glyma.01G000100",
          chromosome: "Chr01",
          start_pos: 1,
          end_pos: 100,
          strand: "+",
          sequences: [
            {
              molecule: "protein",
              availability: "unavailable",
              reason: "no_sequence_store:protein",
              length: null,
              checksum: null,
              sequence: null,
            },
          ],
          model_evidence: { kind: "predicted", source: "AUGUSTUS" },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const detail = await getGene("Glyma.01G000100");
    expect(detail.sequences?.[0].availability).toBe("unavailable");
    expect(detail.sequences?.[0].sequence).toBeNull();
    expect(detail.model_evidence?.kind).toBe("predicted");
  });
});
