import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { httpPost } = vi.hoisted(() => ({ httpPost: vi.fn() }));

vi.mock("@soymutdb/api-client", () => ({
  http: { post: httpPost },
}));

import {
  MULTIPART_PART_SIZE,
  fetchModulePreview,
  uploadModuleFile,
} from "./module-import-upload";

class MockXMLHttpRequest {
  static instances: MockXMLHttpRequest[] = [];

  status = 200;
  body: Document | XMLHttpRequestBodyInit | null = null;
  readonly upload = {
    onprogress: null as ((event: ProgressEvent) => void) | null,
  };
  onload: ((event: ProgressEvent) => void) | null = null;
  onerror: ((event: ProgressEvent) => void) | null = null;

  open = vi.fn();
  getResponseHeader = vi.fn((name: string) => (name.toLowerCase() === "etag" ? '"etag-1"' : null));
  send = vi.fn((body: Document | XMLHttpRequestBodyInit | null) => {
    this.body = body;
    this.onload?.(new ProgressEvent("load"));
  });

  constructor() {
    MockXMLHttpRequest.instances.push(this);
  }
}

beforeEach(() => {
  httpPost.mockReset();
  MockXMLHttpRequest.instances = [];
  vi.stubGlobal("XMLHttpRequest", MockXMLHttpRequest as unknown as typeof XMLHttpRequest);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("uploadModuleFile", () => {
  it("uploads File slices without reading the entire file into an ArrayBuffer", async () => {
    httpPost
      .mockResolvedValueOnce({
        upload_id: "upload-1",
        object_key: "data/1/genes.tsv",
        parts: [
          { part_number: 1, url: "https://storage.example.test/part-1" },
          { part_number: 2, url: "https://storage.example.test/part-2" },
        ],
      })
      .mockResolvedValueOnce({
        upload_id: "upload-1",
        object_key: "data/1/genes.tsv",
        sha256: "a".repeat(64),
        parts: [
          { part_number: 1, etag: "etag-1" },
          { part_number: 2, etag: "etag-1" },
        ],
      });
    const file = new File(
      [new Uint8Array(MULTIPART_PART_SIZE + 3)],
      "genes.tsv",
      { type: "text/tab-separated-values" },
    );
    const fullRead = vi.fn(() => {
      throw new Error("the complete File must not be read into memory");
    });
    Object.defineProperty(file, "arrayBuffer", { value: fullRead });

    await expect(
      uploadModuleFile({ filename: file.name, type: "module_tsv", file }),
    ).resolves.toEqual({ object_key: "data/1/genes.tsv", sha256: "a".repeat(64) });

    expect(fullRead).not.toHaveBeenCalled();
    expect(MockXMLHttpRequest.instances).toHaveLength(2);
    expect(MockXMLHttpRequest.instances.map((xhr) => (xhr.body as Blob).size)).toEqual([
      MULTIPART_PART_SIZE,
      3,
    ]);
    expect(httpPost).toHaveBeenLastCalledWith(
      "/admin/imports/uploads/multipart/upload-1/complete",
      expect.objectContaining({
        json: {
          object_key: "data/1/genes.tsv",
          parts: [
            { part_number: 1, etag: "etag-1" },
            { part_number: 2, etag: "etag-1" },
          ],
        },
      }),
    );
  });
});

describe("fetchModulePreview", () => {
  it("sends only a bounded local file slice to the real inspection endpoint", async () => {
    httpPost.mockResolvedValueOnce({
      module_key: "genes",
      filename: "genes.tsv",
      headers: ["gene_id", "chromosome", "start", "end"],
      row_count: 1,
      rows: [{ gene_id: "G1", chromosome: "Chr01", start: 1, end: 9 }],
      truncated: false,
      checksum_sha256: "b".repeat(64),
      validation: { ok: true, error_count: 0, errors: [] },
    });
    const file = new File(["gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n"], "genes.tsv", {
      type: "text/tab-separated-values",
    });
    const fullRead = vi.fn(() => {
      throw new Error("the complete File must not be read for preview");
    });
    Object.defineProperty(file, "arrayBuffer", { value: fullRead });

    await expect(
      fetchModulePreview({ filename: file.name, moduleKey: "genes", file }),
    ).resolves.toMatchObject({
      status: "available",
      rows: [{ gene_id: "G1" }],
    });

    expect(fullRead).not.toHaveBeenCalled();
    expect(httpPost).toHaveBeenCalledWith(
      "/admin/modules/genes/inspect",
      expect.objectContaining({
        json: expect.objectContaining({ filename: "genes.tsv", content_base64: expect.any(String) }),
      }),
    );
  });
});
