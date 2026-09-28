import { afterEach, describe, expect, it, vi } from "vitest";
import { http } from "./auth";
import { searchVariants } from "./variants";

vi.mock("./auth", () => ({ http: { get: vi.fn() } }));

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
});
