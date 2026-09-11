import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@soymutdb/api-client", () => ({
  requestUpload: vi.fn(),
  submitAnalysis: vi.fn(),
}));

vi.mock("../analyses-local", () => ({
  recordRecentJob: vi.fn(),
}));

import {
  MAX_ANALYSIS_FILE_BYTES,
  calculateFileSha256,
  calculateUploadProgress,
  postWithProgress,
} from "../analyses-upload";

class FakeXMLHttpRequest {
  static instances: FakeXMLHttpRequest[] = [];

  readonly upload = {
    onprogress: null as ((event: ProgressEvent) => void) | null,
  };
  readonly requestHeaders: Array<[string, string]> = [];
  method = "";
  url = "";
  status = 0;
  body: unknown;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXMLHttpRequest.instances.push(this);
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.requestHeaders.push([name, value]);
  }

  send(body: unknown) {
    this.body = body;
  }

  emitProgress(loaded: number, total: number) {
    this.upload.onprogress?.({
      lengthComputable: true,
      loaded,
      total,
    } as ProgressEvent);
  }

  finish(status: number) {
    this.status = status;
    this.onload?.();
  }
}

describe("calculateFileSha256", () => {
  it("returns the canonical lowercase SHA-256 hex digest", async () => {
    const file = new File(["abc"], "reads.fastq");

    const checksum = await calculateFileSha256(file);

    expect(checksum).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
    expect(checksum).toMatch(/^[0-9a-f]{64}$/);
  });

  it("rejects files above the server's 500 MiB limit before reading them", async () => {
    const arrayBuffer = vi.fn();
    const file = {
      name: "too-large.fastq",
      size: MAX_ANALYSIS_FILE_BYTES + 1,
      arrayBuffer,
    } as unknown as File;

    await expect(calculateFileSha256(file)).rejects.toThrow(/500 MiB/);
    expect(arrayBuffer).not.toHaveBeenCalled();
  });

  it("hashes large files as bounded slices without calling File.arrayBuffer", async () => {
    const chunkSize = 4 * 1024 * 1024;
    const file = new File([new Uint8Array(chunkSize * 2 + 19).fill(0x61)], "reads.fastq");
    const fileArrayBuffer = vi.spyOn(file, "arrayBuffer");
    const slice = vi.spyOn(file, "slice");

    const checksum = await calculateFileSha256(file);

    // Digest of a 2-chunk + 19-byte buffer filled with 0x61 ("a"). Verified
    // independently with Node crypto; the previous constant was wrong.
    expect(checksum).toBe("76f3cc3daad525bf8ec71c73b9b389dd2db501a7f7482d7cdc1b2dbb61ec71d7");
    expect(fileArrayBuffer).not.toHaveBeenCalled();
    expect(slice).toHaveBeenCalledTimes(3);
    for (const [start, end] of slice.mock.calls) {
      expect((end ?? file.size) - (start ?? 0)).toBeLessThanOrEqual(chunkSize);
    }
  });

  it("surfaces chunk-read failures", async () => {
    const file = new File(["abc"], "reads.fastq");
    vi.spyOn(file, "slice").mockReturnValue({
      arrayBuffer: vi.fn().mockRejectedValue(new Error("read unavailable")),
    } as unknown as Blob);

    await expect(calculateFileSha256(file)).rejects.toThrow(
      /calculate SHA-256.*reads\.fastq/i,
    );
  });
});

describe("postWithProgress", () => {
  beforeEach(() => {
    FakeXMLHttpRequest.instances = [];
    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("POSTs all presigned fields in order with file last and leaves Content-Type unset", async () => {
    const file = new File(["reads"], "reads.fastq", {
      type: "application/octet-stream",
    });
    const onProgress = vi.fn();
    const upload = postWithProgress(
      "https://objects.example.test/upload",
      "POST",
      {
        key: "analyses/job/input/reads.fastq",
        policy: "signed-policy",
        "x-amz-signature": "signature",
      },
      file,
      onProgress,
    );
    const xhr = FakeXMLHttpRequest.instances[0]!;

    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("https://objects.example.test/upload");
    expect(xhr.requestHeaders).toEqual([]);
    expect(xhr.body).toBeInstanceOf(FormData);
    expect(Array.from((xhr.body as FormData).entries())).toEqual([
      ["key", "analyses/job/input/reads.fastq"],
      ["policy", "signed-policy"],
      ["x-amz-signature", "signature"],
      ["file", file],
    ]);

    // XHR totals include multipart framing, so progress must use event.total
    // instead of comparing transferred bytes with File.size.
    xhr.emitProgress(75, 150);
    expect(onProgress).toHaveBeenLastCalledWith(0.5);

    xhr.finish(204);
    await expect(upload).resolves.toBeUndefined();
    expect(onProgress).toHaveBeenLastCalledWith(1);
  });

  it("fails closed before creating an XHR for a non-POST upload method", async () => {
    await expect(
      postWithProgress("https://objects.example.test/upload", "PUT", {}, new File([], "x"), vi.fn()),
    ).rejects.toThrow(/unsupported.*PUT.*expected POST/i);

    expect(FakeXMLHttpRequest.instances).toHaveLength(0);
  });

  it("rejects an unsuccessful object-store response", async () => {
    const upload = postWithProgress(
      "https://objects.example.test/upload",
      "POST",
      {},
      new File(["reads"], "reads.fastq"),
      vi.fn(),
    );
    const xhr = FakeXMLHttpRequest.instances[0]!;
    const rejection = expect(upload).rejects.toThrow(/HTTP 403/);

    xhr.finish(403);

    await rejection;
  });
});

describe("calculateUploadProgress", () => {
  it("weights the active file by bytes and caps upload progress below submission", () => {
    expect(
      calculateUploadProgress({
        completedBytes: 100,
        totalBytes: 400,
        currentFileBytes: 300,
        currentFileRatio: 0.5,
        completedFiles: 1,
        totalFiles: 2,
      }),
    ).toBe(63);

    expect(
      calculateUploadProgress({
        completedBytes: 400,
        totalBytes: 400,
        currentFileBytes: 0,
        currentFileRatio: 1,
        completedFiles: 2,
        totalFiles: 2,
      }),
    ).toBe(99);
  });

  it("falls back to per-file progress when every file is empty", () => {
    expect(
      calculateUploadProgress({
        completedBytes: 0,
        totalBytes: 0,
        currentFileBytes: 0,
        currentFileRatio: 0.5,
        completedFiles: 1,
        totalFiles: 2,
      }),
    ).toBe(75);

    expect(
      calculateUploadProgress({
        completedBytes: 0,
        totalBytes: 0,
        currentFileBytes: 0,
        currentFileRatio: Number.NaN,
        completedFiles: 0,
        totalFiles: 0,
      }),
    ).toBe(0);
  });
});
