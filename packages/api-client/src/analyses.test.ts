/**
 * Tests for analyses API functions.
 *
 * Mocks `globalThis.fetch` and verifies URL, method, JSON body, response
 * parsing, and that the Bearer token is attached (all analyses endpoints
 * require the researcher role or higher).
 */

import { setAuthTokens, clearAuth } from "./client";
import {
  requestUpload,
  submitAnalysis,
  getAnalysis,
  getAnalysisDownload,
} from "./analyses";

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

describe("analyses (auth)", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({}));
    setAuthTokens("test-token");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    clearAuth();
  });

  // -------------------------------------------------------------------------
  // requestUpload
  // -------------------------------------------------------------------------
  describe("requestUpload", () => {
    const checksum = "a".repeat(64);

    it("POSTs filename/size/checksum to /analyses/uploads with Bearer and parses response", async () => {
      const presigned = {
        upload_url: "https://s3.example.com/analyses/abc/input/s.fastq",
        upload_method: "POST" as const,
        upload_fields: { key: "analyses/abc/input/s.fastq" },
        object_key: "analyses/abc/input/s.fastq",
        expires_in: 3600,
      };
      vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(presigned));

      const result = await requestUpload("s.fastq", 1024, checksum);

      const [url, init] = lastFetchCall();
      expect(url).toBe(`${API_BASE}/analyses/uploads`);
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({
        filename: "s.fastq",
        size: 1024,
        checksum_sha256: checksum,
      });
      expect(new Headers(init.headers).get("Authorization")).toBe(
        "Bearer test-token",
      );
      expect(result).toEqual(presigned);
    });

    it("includes content_type when provided", async () => {
      vi.mocked(fetch).mockResolvedValueOnce(
        jsonResponse({
          upload_url: "u",
          upload_method: "POST",
          upload_fields: {},
          object_key: "k",
          expires_in: 3600,
        }),
      );

      await requestUpload("s.fastq", 2048, checksum, "application/gzip");

      const [, init] = lastFetchCall();
      expect(JSON.parse(init.body as string)).toEqual({
        filename: "s.fastq",
        size: 2048,
        checksum_sha256: checksum,
        content_type: "application/gzip",
      });
    });

    it("rejects a checksum that is not 64 lowercase hexadecimal characters", async () => {
      await expect(
        requestUpload("s.fastq", 1024, "A".repeat(64)),
      ).rejects.toThrow(/64 lowercase hexadecimal/i);

      expect(fetch).not.toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------------
  // submitAnalysis
  // -------------------------------------------------------------------------
  describe("submitAnalysis", () => {
    it("POSTs input_objects/params to /analyses/{type}/submit and parses response", async () => {
      const submitted = { job_id: "job-1", status: "queued" as const };
      vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(submitted));

      const result = await submitAnalysis("fastp", {
        inputObjects: ["analyses/abc/input/s.fastq"],
        params: { trim_front: 10 },
      });

      const [url, init] = lastFetchCall();
      expect(url).toBe(`${API_BASE}/analyses/fastp/submit`);
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({
        input_objects: ["analyses/abc/input/s.fastq"],
        params: { trim_front: 10 },
      });
      expect(new Headers(init.headers).get("Authorization")).toBe(
        "Bearer test-token",
      );
      expect(result).toEqual(submitted);
    });

    it("defaults params to an empty object", async () => {
      vi.mocked(fetch).mockResolvedValueOnce(
        jsonResponse({ job_id: "job-2", status: "queued" }),
      );

      await submitAnalysis("scanpy", { inputObjects: ["analyses/x/y.h5ad"] });

      const [, init] = lastFetchCall();
      expect(JSON.parse(init.body as string)).toEqual({
        input_objects: ["analyses/x/y.h5ad"],
        params: {},
      });
    });
  });

  // -------------------------------------------------------------------------
  // getAnalysis
  // -------------------------------------------------------------------------
  describe("getAnalysis", () => {
    it("GETs /analyses/{job_id} with Bearer and parses the job payload", async () => {
      const job = {
        job_id: "job-1",
        analysis_type: "fastp" as const,
        status: "running" as const,
        error_message: null,
        result: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:01Z",
      };
      vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(job));

      const result = await getAnalysis("job-1");

      const [url, init] = lastFetchCall();
      expect(url).toBe(`${API_BASE}/analyses/job-1`);
      expect(init.method).toBe("GET");
      expect(init.body).toBeUndefined();
      expect(new Headers(init.headers).get("Authorization")).toBe(
        "Bearer test-token",
      );
      expect(result).toEqual(job);
    });
  });

  // -------------------------------------------------------------------------
  // getAnalysisDownload
  // -------------------------------------------------------------------------
  describe("getAnalysisDownload", () => {
    it("GETs /analyses/{job_id}/download with object_key query param", async () => {
      const presigned = {
        download_url: "https://s3.example.com/analyses/job-1/out.tsv",
        expires_in: 600,
      };
      vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(presigned));

      const result = await getAnalysisDownload("job-1", "analyses/job-1/out.tsv");

      const [url, init] = lastFetchCall();
      expect(url).toBe(
        `${API_BASE}/analyses/job-1/download?object_key=analyses%2Fjob-1%2Fout.tsv`,
      );
      expect(init.method).toBe("GET");
      expect(new Headers(init.headers).get("Authorization")).toBe(
        "Bearer test-token",
      );
      expect(result).toEqual(presigned);
    });
  });
});
