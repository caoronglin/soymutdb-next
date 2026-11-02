import { getBlastHits, getBlastJob, getBlastJobs, resolveBlastHitGenomeTarget, submitBlastJob } from "./blast";
import { setReleaseId } from "./client";
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

  afterEach(() => { setReleaseId(null); vi.restoreAllMocks(); });

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

  function json(body: unknown, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }
  const job = { release_id: 4, assembly_name: "Wm82.a4.v1" };
  const gene = { gene_id: "Glyma.01G000100", assembly_id: "7", chromosome: "chr01", start_pos: 12000, end_pos: 15000 };

  it("preserves API job provenance through normalization", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({ job_id: "job", database_id: 1, ...job }));
    expect(await getBlastJob("job")).toMatchObject({ id: "job", database: "1", ...job });
  });
  it("uses exact assembly/gene records and overrides active release headers", async () => {
    setReleaseId("9");
    vi.mocked(fetch).mockResolvedValueOnce(json([{ id: 7, name: job.assembly_name }]))
      .mockResolvedValueOnce(json(gene));
    expect(await resolveBlastHitGenomeTarget(job, gene.gene_id)).toEqual({ release: "4", assembly: job.assembly_name, locus: "chr01:12000-15000" });
    expect(fetch).toHaveBeenCalledTimes(2);
    for (const [input, init] of vi.mocked(fetch).mock.calls) {
      expect(new Headers(init?.headers).get("X-SoyMutDB-Release")).toBe("4");
      expect(new URL(String(input), "http://localhost").searchParams.has("release_id")).toBe(false);
    }
    const geneUrl = new URL(String(vi.mocked(fetch).mock.calls[1][0]), "http://localhost");
    expect(geneUrl.searchParams.get("assembly_id")).toBe("7");
  });
  it("does not request data for an unproven job context", async () => {
    expect(await resolveBlastHitGenomeTarget({ release_id: null }, "gene")).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("rejects ambiguous assembly names instead of choosing one", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json([{ id: 7, name: job.assembly_name }, { id: 8, name: job.assembly_name }]));
    expect(await resolveBlastHitGenomeTarget(job, gene.gene_id)).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("does not issue an unscoped lookup if an assembly response lacks its identity", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json([{ name: job.assembly_name }]));
    expect(await resolveBlastHitGenomeTarget(job, gene.gene_id)).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("does not strip protein isoform suffixes or fuzzy-match unknown IDs", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json([{ id: 7, name: job.assembly_name }]))
      .mockResolvedValueOnce(json({ error: { code: "not_found", message: "missing" } }, 404));
    expect(await resolveBlastHitGenomeTarget(job, "protein/a.1")).toBeNull();
    expect(String(vi.mocked(fetch).mock.calls[1][0])).toContain("/genes/protein%2Fa.1?");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it.each([{ assembly_id: "8" }, { start_pos: 0 }, { end_pos: 1 }, { chromosome: " " }, { gene_id: "another" }])("rejects an untrusted gene interval %j", async (invalid) => {
    vi.mocked(fetch).mockResolvedValueOnce(json([{ id: 7, name: job.assembly_name }]))
      .mockResolvedValueOnce(json({ ...gene, ...invalid }));
    expect(await resolveBlastHitGenomeTarget(job, gene.gene_id)).toBeNull();
  });

  it("uses the implemented jobs list and result routes", async () => {
    await getBlastJobs({ page: 1, page_size: 20 });
    await getBlastHits("job-1", { limit: 25, offset: 0 });

    const [jobsUrl] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const [hitsUrl] = vi.mocked(fetch).mock.calls[1] as [string, RequestInit];
    expect(jobsUrl).toContain("/blast/jobs?");
    expect(hitsUrl).toContain("/blast/jobs/job-1/results?");
    expect(new URL(jobsUrl, "http://localhost").searchParams.get("page")).toBe("1");
    expect(new URL(jobsUrl, "http://localhost").searchParams.get("page_size")).toBe("20");
    expect(new URL(hitsUrl, "http://localhost").searchParams.get("limit")).toBe("25");
    expect(new URL(hitsUrl, "http://localhost").searchParams.get("offset")).toBe("0");
  });
});
