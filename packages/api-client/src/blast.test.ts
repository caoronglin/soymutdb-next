import { getBlastHits, getBlastJobs, submitBlastJob } from "./blast";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("BLAST client contract", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
      Promise.resolve(new Response(JSON.stringify(
        String(input).includes("/results")
          ? { hits: [], total_hits: 0 }
          : { items: [], total: 0, page: 1, page_size: 20 },
      ), {
        status: 200,
        headers: { "content-type": "application/json" },
      })),
    );
  });

  afterEach(() => vi.restoreAllMocks());

  it("submits the API schema instead of the legacy flat payload", async () => {
    await submitBlastJob({
      program: "blastn",
      database: "williams82_cds",
      sequence: ">q\nACGTACGTACGT",
      e_value: 1e-5,
      max_hits: 50,
    });

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      program: "blastn",
      database: "williams82_cds",
      query_sequence: ">q\nACGTACGTACGT",
      parameters: { evalue: 1e-5, max_target_seqs: 50 },
    });
  });

  it("uses the implemented jobs list and result routes", async () => {
    await getBlastJobs({ cursor: "c1", limit: 10 });
    await getBlastHits("job-1", { cursor: "c1", limit: 25 });

    const [jobsUrl] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const [hitsUrl] = vi.mocked(fetch).mock.calls[1] as [string, RequestInit];
    expect(jobsUrl).toContain("/blast/jobs?");
    expect(hitsUrl).toContain("/blast/jobs/job-1/results?");
    expect(new URL(hitsUrl, "http://localhost").searchParams.get("cursor")).toBe("c1");
    expect(new URL(hitsUrl, "http://localhost").searchParams.get("limit")).toBe("25");
  });
});
