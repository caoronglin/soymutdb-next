import { searchGenes } from "./genes";
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
