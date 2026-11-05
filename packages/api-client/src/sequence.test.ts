/**
 * Tests for the `/tools/sequence/*` client.
 *
 * Covers the three things that are easy to get silently wrong here: the URL
 * prefix, the absence of an Authorization header (these are public
 * utilities), and — most importantly — reading the *kernel* code out of the
 * error envelope rather than the API-level `validation_error`.
 */

import {
  countSequenceCharacters,
  isKernelUnavailable,
  SEQUENCE_KERNEL_CODES,
  sequenceApi,
  sequenceKernelCode,
} from "./sequence";
import { ApiError } from "./client";

const BASE = "/api/v1/tools/sequence";

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

function assertNoAuth(init: RequestInit): void {
  expect(new Headers(init.headers).get("Authorization")).toBeNull();
}

/** Build the repo's unified error envelope with a kernel code inside. */
function kernelErrorEnvelope(code: string, message = "rejected"): unknown {
  return {
    error: { code: "validation_error", message, details: { code } },
    request_id: "req-1",
    status_code: 422,
  };
}

describe("sequence client (public, no auth)", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({}));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("posts the reverse complement to the prefixed URL without auth", async () => {
    await sequenceApi.reverseComplement({ sequence: "ATGC", preserve_case: true });
    const [url, init] = lastFetchCall();
    expect(url).toBe(`${BASE}/reverse-complement`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      sequence: "ATGC",
      preserve_case: true,
    });
    assertNoAuth(init);
  });

  it("sends the match target as a discriminated inline object", async () => {
    await sequenceApi.match({
      pattern: "ACGT",
      target: { kind: "inline", sequence: "GGACGTAA" },
    });
    const [, init] = lastFetchCall();
    const body = JSON.parse(init.body as string);
    expect(body.target).toEqual({ kind: "inline", sequence: "GGACGTAA" });
    // Omitted defaults stay omitted — the server fills them.
    expect("assembly" in body).toBe(false);
    expect("max_hits" in body).toBe(false);
  });

  it("keeps align query and target as two separate fields", async () => {
    await sequenceApi.align({ query: "ACGT", target: "ACGA", mode: "global" });
    const [url, init] = lastFetchCall();
    expect(url).toBe(`${BASE}/align`);
    expect(JSON.parse(init.body as string)).toMatchObject({
      query: "ACGT",
      target: "ACGA",
      mode: "global",
    });
  });

  it("hits /stats, /orfs, /translate and /kmers on their own paths", async () => {
    await sequenceApi.stats({ sequence: "ATGC" });
    expect(lastFetchCall()[0]).toBe(`${BASE}/stats`);
    await sequenceApi.orfs({ sequence: "ATGC", min_len: 30 });
    expect(lastFetchCall()[0]).toBe(`${BASE}/orfs`);
    await sequenceApi.translate({ sequence: "ATGGCC", frame: 1 });
    expect(lastFetchCall()[0]).toBe(`${BASE}/translate`);
    await sequenceApi.kmers({ sequence: "ATGCATGC", k: 3 });
    expect(lastFetchCall()[0]).toBe(`${BASE}/kmers`);
  });

  it("inspects a format by base64 payload, not by path", async () => {
    await sequenceApi.inspect("fasta", "PkFCQw==");
    const [url, init] = lastFetchCall();
    expect(url).toBe(`${BASE}/inspect`);
    expect(JSON.parse(init.body as string)).toEqual({ fmt: "fasta", data: "PkFCQw==" });
  });

  it("reads capabilities with GET and without auth", async () => {
    await sequenceApi.capabilities();
    const [url, init] = lastFetchCall();
    expect(url).toBe(`${BASE}/capabilities`);
    expect(init.method ?? "GET").toBe("GET");
    assertNoAuth(init);
  });
});

describe("sequenceKernelCode", () => {
  it("reads the kernel code out of error.details.code", () => {
    const err = new ApiError("rejected", 422, "validation_error", kernelErrorEnvelope("UNKNOWN_GENETIC_CODE"));
    // The API-level code is generic; the kernel's own code is what a user fixes.
    expect(err.code).toBe("validation_error");
    expect(sequenceKernelCode(err)).toBe("UNKNOWN_GENETIC_CODE");
  });

  it("returns null for an unknown kernel code rather than guessing", () => {
    const err = new ApiError("rejected", 422, "validation_error", kernelErrorEnvelope("SOMETHING_NEW"));
    expect(sequenceKernelCode(err)).toBeNull();
  });

  it("returns null when there is no envelope at all", () => {
    expect(sequenceKernelCode(new ApiError("busy", 429, "rate_limit_exceeded"))).toBeNull();
    expect(sequenceKernelCode(new Error("boom"))).toBeNull();
    expect(sequenceKernelCode(null)).toBeNull();
  });

  it("does not mistake an absent kernel for a rejected input", () => {
    const unavailable = new ApiError("sequence engine unavailable", 503, "service_unavailable");
    expect(isKernelUnavailable(unavailable)).toBe(true);
    expect(sequenceKernelCode(unavailable)).toBeNull();
    expect(isKernelUnavailable(new ApiError("rejected", 422, "validation_error"))).toBe(false);
  });

  it("surfaces a kernel code that arrived through a real request failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(kernelErrorEnvelope("BUDGET_EXCEEDED"), 422),
    );
    const failure = await sequenceApi.align({ query: "A", target: "A" }).then(
      () => null,
      (err: unknown) => err,
    );
    expect(failure).toBeInstanceOf(ApiError);
    expect(sequenceKernelCode(failure)).toBe("BUDGET_EXCEEDED");
  });

  it("keeps the published code list free of duplicates", () => {
    expect(new Set(SEQUENCE_KERNEL_CODES).size).toBe(SEQUENCE_KERNEL_CODES.length);
  });
});

describe("countSequenceCharacters", () => {
  it("ignores FASTA headers and blank lines", () => {
    expect(countSequenceCharacters(">seq1\nATGC\nATGC\n\n>seq2\nGGCC\n")).toBe(12);
  });

  it("counts a bare sequence as-is", () => {
    expect(countSequenceCharacters("ATGCATGC")).toBe(8);
  });

  it("does not count a header line as sequence", () => {
    expect(countSequenceCharacters(">only_a_header\n")).toBe(0);
  });

  it("measures a FASTA file by residues, not by bytes", () => {
    // Two records of 60 residues each, wrapped at 60, with two headers.
    const record = (name: string) => `>${name}\n${"A".repeat(60)}\n`;
    expect(countSequenceCharacters(record("a") + record("b"))).toBe(120);
  });
});
