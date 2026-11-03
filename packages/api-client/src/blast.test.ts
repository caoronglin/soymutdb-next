import { hasCompatibleBlastQueryAlphabet, compatibleBlastDatabases, type BlastProgram, getBlastHits, getBlastJob, getBlastJobs, getPublicBlastDatabases, getPublicBlastJob, getPublicBlastResults, resolveBlastHitGenomeTarget, submitBlastJob, submitPublicBlastJob } from "./blast";
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

  it.each(["blastn", "blastp", "blastx", "tblastn", "tblastx"] as BlastProgram[])("preserves NCBI %s and per-HSP query IDs", async (program) => {
    vi.mocked(fetch).mockResolvedValueOnce(json({ job: { job_id: "search", database_id: 1, engine: "ncbi_blast", program }, access_token: "secret", expires_at: "2030-01-01T00:00:00Z" }, 201));
    await submitPublicBlastJob({ program, engine: "ncbi_blast", database: "db", sequence: ">q1\nACGTACGTACGT" });
    const body = JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body));
    expect(body).toMatchObject({ program, engine: "ncbi_blast" });
    vi.mocked(fetch).mockResolvedValueOnce(json({ status: "completed", hits: [{ query_id: "q2", subject_id: "subject", hsp_num: 1 }], total_hits: 1 }));
    const result = await getPublicBlastResults("search", "secret");
    expect(result.items[0].query_id).toBe("q2");
  });

  it("validates query alphabet by program rather than target database", () => {
    expect(hasCompatibleBlastQueryAlphabet(">q\nMKKLLLLLLLL", "tblastn")).toBe(true);
    expect(hasCompatibleBlastQueryAlphabet(">q\nMKKLLLLLLLL", "blastx")).toBe(false);
    expect(hasCompatibleBlastQueryAlphabet(">q\nACGTNNNNACGT", "blastx")).toBe(true);
  });

  it("offers only ready active indexes of the selected engine and biological database type", () => {
    const rows = [
      { id: 1, name: "protein", engine: "ncbi_blast" as const, db_type: "prot" as const, build_status: "ready" as const, is_active: true, assembly_id: 1 },
      { id: 2, name: "genome", engine: "ncbi_blast" as const, db_type: "nucl" as const, build_status: "ready" as const, is_active: true, assembly_id: 1 },
      { id: 3, name: "fast", engine: "diamond" as const, db_type: "prot" as const, build_status: "ready" as const, is_active: true, assembly_id: 1 },
    ];
    expect(compatibleBlastDatabases(rows, "ncbi_blast", "blastn").map((row) => row.name)).toEqual(["genome"]);
    expect(compatibleBlastDatabases(rows, "ncbi_blast", "blastx").map((row) => row.name)).toEqual(["protein"]);
    expect(compatibleBlastDatabases(rows, "ncbi_blast", "tblastn").map((row) => row.name)).toEqual(["genome"]);
    expect(compatibleBlastDatabases(rows, "diamond", "blastp").map((row) => row.name)).toEqual(["fast"]);
    expect(compatibleBlastDatabases([{ ...rows[0], build_status: "building" }], "ncbi_blast", "blastp")).toEqual([]);
  });

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
      engine: "ncbi_blast",
      database: "williams82_cds",
      query_sequence: ">q\nACGTACGTACGT",
      parameters: { evalue: 1e-5, max_target_seqs: 50 },
    });
  });


  it("rejects unsupported public programs before making a request", async () => {
    expect(() => submitPublicBlastJob({ program: "blastn", engine: "diamond", database: "protein-v4", sequence: "MKKLLLLLLLL" })).toThrow("blastp only");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("uses public BLAST endpoints without auth refresh or URL tokens", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({ job: { job_id: "public-job", database_id: 1, status: "pending" }, access_token: "secret-token", expires_at: "2030-01-01T00:00:00Z" }));
    const created = await submitPublicBlastJob({ program: "blastp", database: "protein-v4", sequence: "MKKLLLLLLLL", e_value: 1e-5, max_hits: 50 });
    expect(created.job.id).toBe("public-job");
    const [input, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(String(input)).toContain("/blast/public/jobs");
    expect(String(input)).not.toContain("secret-token");
    expect(new Headers(init.headers).get("Authorization")).toBeNull();
    expect(init.credentials).toBe("omit");
    expect(init.cache).toBe("no-store");

    vi.mocked(fetch).mockResolvedValueOnce(json({ job_id: "public-job", database_id: 1, status: "completed" }));
    await getPublicBlastJob("public-job", "secret-token");
    const [, statusInit] = vi.mocked(fetch).mock.calls[1] as [string, RequestInit];
    expect(new Headers(statusInit.headers).get("X-Blast-Token")).toBe("secret-token");
    expect(String(vi.mocked(fetch).mock.calls[1][0])).not.toContain("secret-token");

    vi.mocked(fetch).mockResolvedValueOnce(json({ job_id: "public-job", status: "completed", hits: [], total_hits: 0, download_url: "https://objects.example/raw.tsv" }));
    const result = await getPublicBlastResults("public-job", "secret-token", { limit: 25, offset: 0 });
    expect(result.download_url).toBe("https://objects.example/raw.tsv");
    expect(new URL(String(vi.mocked(fetch).mock.calls[2][0]), "http://localhost").searchParams.get("limit")).toBe("25");

    vi.mocked(fetch).mockResolvedValueOnce(json([]));
    await getPublicBlastDatabases();
    const [, databaseInit] = vi.mocked(fetch).mock.calls[3] as [string, RequestInit];
    expect(databaseInit.credentials).toBe("omit");
    expect(new Headers(databaseInit.headers).get("Authorization")).toBeNull();
  });
  function json(body: unknown, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }
  const job = { id: "job-1", release_id: 4, assembly_name: "Wm82.a4.v1" };
  const resolved = {
    status: "resolved", gene_id: "Glyma.01G000100", chromosome: "chr01",
    start: 12000, end: 15000, strand: "+", release_id: 4, assembly_id: 7,
    assembly_name: "Wm82.a4.v1", locus: "chr01:12000-15000",
    resolution: "gene_accession",
  };

  it("preserves API job provenance through normalization", async () => {
    const provenance = { release_id: 4, assembly_name: job.assembly_name };
    vi.mocked(fetch).mockResolvedValueOnce(json({ job_id: "job", database_id: 1, ...provenance }));
    expect(await getBlastJob("job")).toMatchObject({ id: "job", database: "1", ...provenance });
  });
  it("resolves a subject through the API's explicit gene relation, never AA coordinates", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json(resolved));
    expect(await resolveBlastHitGenomeTarget(job, "Glyma.01G000100")).toMatchObject({
      release: "4", assembly: job.assembly_name, locus: "chr01:12000-15000",
      resolution: "gene_accession",
    });
    expect(fetch).toHaveBeenCalledTimes(1);
    const [input, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(String(input)).toContain("/blast/jobs/job-1/hits/Glyma.01G000100/genome-target");
    // No alignment coordinates are ever sent to build a genome location.
    expect(String(input)).not.toMatch(/subject_start|subject_end|qstart|sstart/);
    expect(init.body).toBeUndefined();
  });
  it("uses the anonymous capability endpoint for public jobs", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json(resolved));
    await resolveBlastHitGenomeTarget(job, "Glyma.01G000100", { publicToken: "secret" });
    const [input, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(String(input)).toContain("/blast/public/jobs/job-1/hits/");
    expect(new Headers(init.headers).get("X-Blast-Token")).toBe("secret");
    expect(init.credentials).toBe("omit");
  });
  it("does not request data for an unproven job context", async () => {
    expect(await resolveBlastHitGenomeTarget({ ...job, release_id: null }, "gene")).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("does not fabricate a locus when the API says the subject is unresolved", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({ status: "unresolved", reason: "subject_not_found" }));
    expect(await resolveBlastHitGenomeTarget(job, "protein.1")).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("rejects a transcript/alias resolution that came from another release or assembly", async () => {
    for (const wrong of [
      { ...resolved, release_id: 5 },
      { ...resolved, assembly_name: "Wm82.a2.v1" },
      { ...resolved, start: 0 },
      { ...resolved, end: 1 },
      { ...resolved, locus: null },
    ]) {
      vi.mocked(fetch).mockResolvedValueOnce(json(wrong));
      expect(await resolveBlastHitGenomeTarget(job, "subject")).toBeNull();
    }
  });
  it("does not strip protein isoform suffixes or fuzzy-match unknown IDs", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({ error: { code: "not_found", message: "missing" } }, 404));
    expect(await resolveBlastHitGenomeTarget(job, "protein/a.1")).toBeNull();
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain("/hits/protein%2Fa.1/genome-target");
    expect(fetch).toHaveBeenCalledTimes(1);
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
