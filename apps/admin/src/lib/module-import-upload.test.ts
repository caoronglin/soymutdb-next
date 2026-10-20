import { beforeEach, describe, expect, it, vi } from "vitest";

import { http } from "@soymutdb/api-client";

import {
  MULTIPART_PART_SIZE,
  describeUploadSource,
  partCountFor,
  uploadModuleFile,
} from "./module-import-upload";

vi.mock("@soymutdb/api-client", () => ({
  http: { post: vi.fn(), get: vi.fn() },
}));

const post = vi.mocked(http.post);

interface FakeXhrInit {
  onload: (() => void) | null;
  onerror: (() => void) | null;
  onabort: (() => void) | null;
  upload: { onprogress: ((event: unknown) => void) | null };
}

class FakeXhr {
  static instances: FakeXhr[] = [];
  static respondWith: (xhr: FakeXhr) => void = (xhr) => xhr.succeed('"etag-1"');

  status = 200;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  upload: FakeXhrInit["upload"] = { onprogress: null };
  aborted = false;
  private headers: Record<string, string> = {};

  constructor() {
    FakeXhr.instances.push(this);
  }

  open() {}
  send() {}

  abort() {
    this.aborted = true;
    this.onabort?.();
  }

  getResponseHeader(name: string): string | null {
    return this.headers[name] ?? null;
  }

  succeed(etag: string | null) {
    if (etag === null) {
      this.headers = {};
    } else {
      this.headers = { ETag: etag };
    }
    this.onload?.();
  }
}

async function waitForParts(count: number): Promise<void> {
  for (let attempt = 0; attempt < 500; attempt += 1) {
    if (FakeXhr.instances.length >= count) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error(`expected ${count} part request(s), saw ${FakeXhr.instances.length}`);
}

function mockSession(parts: number[]) {
  post
    .mockResolvedValueOnce({
      upload_id: "upload-1",
      object_key: "data/1/genes.tsv",
      parts: parts.map((part_number) => ({ part_number, url: `https://s3.test/${part_number}` })),
    })
    .mockResolvedValueOnce({
      upload_id: "upload-1",
      object_key: "data/1/genes.tsv",
      sha256: "a".repeat(64),
      parts: [],
    });
}

function makeFile(bytes: number, name = "genes.tsv"): File {
  return new File([new Uint8Array(bytes)], name, { type: "text/tab-separated-values" });
}

beforeEach(() => {
  FakeXhr.instances = [];
  FakeXhr.respondWith = (xhr) => xhr.succeed('"etag-1"');
  post.mockReset();
  vi.stubGlobal("XMLHttpRequest", FakeXhr as unknown as typeof XMLHttpRequest);
});

describe("partCountFor", () => {
  it("keeps every non-final part at or above the S3 minimum", () => {
    expect(partCountFor(0)).toBe(1);
    expect(partCountFor(1)).toBe(1);
    expect(partCountFor(MULTIPART_PART_SIZE)).toBe(1);
    expect(partCountFor(MULTIPART_PART_SIZE + 1)).toBe(2);
    expect(partCountFor(MULTIPART_PART_SIZE * 2)).toBe(2);
    expect(partCountFor(MULTIPART_PART_SIZE * 2 + 1)).toBe(3);
  });
});

describe("describeUploadSource", () => {
  const base = {
    filename: "genes.tsv",
    size: 10,
    lastModified: 5,
    type: "module_tsv",
    moduleKey: "genes",
    dataSetId: 1,
  };

  it("treats the same file, module key and data set as one upload", () => {
    expect(describeUploadSource(base)).toBe(describeUploadSource({ ...base, moduleKey: " genes " }));
  });

  it("separates a different file, module key or data set", () => {
    const identity = describeUploadSource(base);
    expect(describeUploadSource({ ...base, lastModified: 6 })).not.toBe(identity);
    expect(describeUploadSource({ ...base, moduleKey: "variants" })).not.toBe(identity);
    // Object keys are bound to their data set server-side, so bytes already in
    // another data set must never be reused.
    expect(describeUploadSource({ ...base, dataSetId: 2 })).not.toBe(identity);
  });
});

describe("uploadModuleFile", () => {
  it("opens a session, PUTs every part and returns the completed object", async () => {
    mockSession([1]);
    const progress: number[] = [];
    const pending = uploadModuleFile({
      filename: "genes.tsv",
      type: "module_tsv",
      file: makeFile(1024),
      dataSetId: 1,
      onProgress: (p) => progress.push(p.percent),
    });

    await waitForParts(1);
    FakeXhr.respondWith(FakeXhr.instances[0]);

    await expect(pending).resolves.toEqual({
      object_key: "data/1/genes.tsv",
      sha256: "a".repeat(64),
    });
    expect(post.mock.calls[0][0]).toBe("/admin/imports/uploads/multipart");
    expect((post.mock.calls[0][1] as { json: unknown }).json).toEqual({
      filename: "genes.tsv",
      type: "module_tsv",
      part_count: 1,
      content_type: "text/tab-separated-values",
      data_set_id: 1,
    });
    expect((post.mock.calls[1][1] as { json: unknown }).json).toEqual({
      object_key: "data/1/genes.tsv",
      parts: [{ part_number: 1, etag: "etag-1" }],
    });
    expect(progress.every((value) => Number.isFinite(value) && value >= 0 && value <= 100)).toBe(true);
  });

  it("completes in ascending part order even when the API hands them out shuffled", async () => {
    const file = makeFile(MULTIPART_PART_SIZE * 2 + 10, "big.tsv");
    mockSession([3, 1, 2]);
    const pending = uploadModuleFile({
      filename: "big.tsv",
      type: "module_tsv",
      file,
      dataSetId: 1,
    });
    for (let index = 0; index < 3; index += 1) {
      await waitForParts(index + 1);
      FakeXhr.respondWith(FakeXhr.instances[index]);
    }
    await pending;
    const completeBody = (post.mock.calls[1][1] as { json: { parts: Array<{ part_number: number }> } }).json;
    expect(completeBody.parts.map((p) => p.part_number)).toEqual([1, 2, 3]);
  });

  it("fails immediately when object storage returns no ETag, instead of after the whole transfer", async () => {
    mockSession([1]);
    FakeXhr.respondWith = (xhr) => xhr.succeed(null);
    const pending = uploadModuleFile({
      filename: "genes.tsv",
      type: "module_tsv",
      file: makeFile(1024),
      dataSetId: 1,
    });
    await waitForParts(1);
    FakeXhr.respondWith(FakeXhr.instances[0]);

    await expect(pending).rejects.toThrow(/did not return an ETag/);
    // The completion call must not be attempted with an empty ETag: the API
    // rejects it and, on any failure, aborts the whole session.
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("aborts an in-flight part request when the caller cancels", async () => {
    mockSession([1, 2]);
    const controller = new AbortController();
    const pending = uploadModuleFile({
      filename: "big.tsv",
      type: "module_tsv",
      file: makeFile(MULTIPART_PART_SIZE + 10, "big.tsv"),
      dataSetId: 1,
      signal: controller.signal,
    });
    await waitForParts(1);
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(FakeXhr.instances[0].aborted).toBe(true);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("does not open a session for an already-cancelled upload", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      uploadModuleFile({
        filename: "genes.tsv",
        type: "module_tsv",
        file: makeFile(1024),
        dataSetId: 1,
        signal: controller.signal,
      }),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(post).not.toHaveBeenCalled();
  });

  it("rejects an empty local file before starting a multipart session", async () => {
    await expect(
      uploadModuleFile({ filename: "empty.tsv", type: "module_tsv", file: makeFile(0, "empty.tsv"), dataSetId: 1 }),
    ).rejects.toThrow(/empty/);
    expect(post).not.toHaveBeenCalled();
    expect(FakeXhr.instances).toHaveLength(0);
  });
});
