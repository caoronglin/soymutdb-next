/**
 * Population-genetics tools client.
 *
 * The transport is mocked (as in `comparative.test.ts`) so these tests assert
 * what each function *builds*: the method, the public path, the body, and that
 * no Bearer token is attached. The `r_squared: null` case is pinned here as a
 * value, not as a formatting decision — the UI must never read it as 0.
 */

import { request } from "./client";
import { computeAlleleFreq, computeDiversity, computeLd } from "./popgen";

vi.mock("./client", () => ({
  request: vi.fn(),
  TimeoutPresets: { CRITICAL: 120_000 },
}));

const mockRequest = vi.mocked(request);

describe("popgen client", () => {
  beforeEach(() => {
    mockRequest.mockReset();
    mockRequest.mockResolvedValue({} as never);
  });

  it("posts the region query anonymously for LD", async () => {
    await computeLd({
      gene_id: "Glyma.01G000100",
    });

    expect(mockRequest).toHaveBeenCalledWith("/tools/ld", {
      method: "POST",
      auth: false,
      json: { gene_id: "Glyma.01G000100" },
      timeoutMs: 120_000,
    });
  });

  it("forwards an interval with all four coordinate fields and no gene id", async () => {
    await computeDiversity({
      assembly: "Wm82.a4.v1",
      chromosome: "chr01",
      start: 1000,
      end: 20000,
      sample_size: 30,
      window_size: 5000,
    });

    expect(mockRequest).toHaveBeenCalledWith("/tools/diversity", {
      method: "POST",
      auth: false,
      json: {
        assembly: "Wm82.a4.v1",
        chromosome: "chr01",
        start: 1000,
        end: 20000,
        sample_size: 30,
        window_size: 5000,
      },
      timeoutMs: 120_000,
    });
  });

  it("forwards the inline genotype matrix untouched", async () => {
    const genotypes = {
      sample_ids: ["s1", "s2"],
      variant_ids: ["v1", "v2"],
      values: [
        [0, 2],
        [1, 1],
      ],
    };

    await computeLd({ assembly: "Wm82.a4.v1", chromosome: "chr01", start: 1, end: 100, genotypes });

    expect(mockRequest).toHaveBeenCalledWith("/tools/ld", {
      method: "POST",
      auth: false,
      json: { assembly: "Wm82.a4.v1", chromosome: "chr01", start: 1, end: 100, genotypes },
      timeoutMs: 120_000,
    });
  });

  it("carries the allele-freq variant cap", async () => {
    await computeAlleleFreq({ gene_id: "Glyma.02G000200", max_variants: 500 });

    expect(mockRequest).toHaveBeenCalledWith("/tools/allelefreq", {
      method: "POST",
      auth: false,
      json: { gene_id: "Glyma.02G000200", max_variants: 500 },
      timeoutMs: 120_000,
    });
  });

  it("leaves r_squared null when the server has no genotype data", async () => {
    mockRequest.mockResolvedValueOnce({
      source: "gene",
      gene_id: "Glyma.01G000100",
      assembly: "Wm82.a4.v1",
      chromosome: "chr01",
      start: 1,
      end: 100,
      n_variants: 2,
      variants: [],
      r_squared: null,
      note: "genotypes required",
      details: null,
    });

    const response = await computeLd({ gene_id: "Glyma.01G000100" });

    // `null` is unknown, not zero: collapsing it here would lose that meaning
    // before the UI ever sees it.
    expect(response.r_squared).toBeNull();
  });
});
