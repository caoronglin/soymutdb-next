import { afterEach, describe, expect, it, vi } from "vitest";
import { http } from "./auth";
import { globalSearch } from "./search";

vi.mock("./auth", () => ({ http: { get: vi.fn() } }));

describe("search client contract", () => {
  afterEach(() => vi.clearAllMocks());

  it("serializes types/cursor/limit and never page_size", async () => {
    vi.mocked(http.get).mockResolvedValueOnce({});
    await globalSearch({ q: "Glyma", types: ["gene"], cursor: "c1", limit: 20 });
    expect(http.get).toHaveBeenCalledWith("/search", {
      params: { q: "Glyma", types: ["gene"], cursor: "c1", limit: 20 },
    });
    expect(vi.mocked(http.get).mock.calls[0][1]?.params).not.toHaveProperty("page_size");
  });
});
