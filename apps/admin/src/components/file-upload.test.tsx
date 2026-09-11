import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { App as AntdApp } from "../lib/antd";
import {
  completeUpload,
  uploadPresign,
  type MediaAsset,
  type UploadPresignResponse,
} from "@soymutdb/api-client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FileUpload from "./file-upload";

// The shared double keeps a stable `t` identity: an inline
// `() => ({ t: ... })` returns a new function per render and makes any
// component with `t` in an effect dependency loop forever. See test/mocks.ts.
vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);

vi.mock("@soymutdb/api-client", () => ({
  completeUpload: vi.fn(),
  uploadPresign: vi.fn(),
}));

const uploadPresignMock = vi.mocked(uploadPresign);
const completeUploadMock = vi.mocked(completeUpload);
const completedAsset = {
  id: "asset-id",
  object_key: "uploads/news/signed-cover.png",
  public_url: "https://cdn.example.test/uploads/news/signed-cover.png",
  original_filename: "cover.png",
  purpose: "news",
  content_type: "image/png",
  size_bytes: 4,
  checksum_sha256: "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
  width: 1,
  height: 1,
  alt_text: null,
  caption: null,
  credit: null,
  is_decorative: false,
  status: "ready",
  uploaded_by: "user-id",
  verified_at: "2026-08-28T00:00:00Z",
  archived_at: null,
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:00:00Z",
  usage_count: 0,
} as MediaAsset;
const messageError = vi.fn();

class MockXMLHttpRequest {
  static instances: MockXMLHttpRequest[] = [];

  method = "";
  url = "";
  status = 0;
  body: Document | XMLHttpRequestBodyInit | null = null;
  onload: ((event: ProgressEvent) => void) | null = null;
  onerror: ((event: ProgressEvent) => void) | null = null;
  upload = {
    onprogress: null as ((event: ProgressEvent) => void) | null,
  };
  open = vi.fn((method: string, url: string) => {
    this.method = method;
    this.url = url;
  });
  setRequestHeader = vi.fn();
  send = vi.fn((body: Document | XMLHttpRequestBodyInit | null = null) => {
    this.body = body;
  });

  constructor() {
    MockXMLHttpRequest.instances.push(this);
  }

  succeed(status = 204) {
    this.status = status;
    this.onload?.(new ProgressEvent("load"));
  }
}

const digestBytes = Uint8Array.from({ length: 32 }, (_, index) => index);
const checksumSha256 =
  "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f";

function makeFile(type = "image/png") {
  const file = new File([Uint8Array.from([1, 2, 3, 4])], "cover.png", {
    type,
  });
  const arrayBuffer = vi
    .fn()
    .mockResolvedValue(Uint8Array.from([1, 2, 3, 4]).buffer);
  Object.defineProperty(file, "arrayBuffer", { value: arrayBuffer });
  return { file, arrayBuffer };
}

function chooseFile(container: HTMLElement, file: File) {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  expect(input).not.toBeNull();
  fireEvent.change(input!, { target: { files: [file] } });
}

beforeEach(() => {
  uploadPresignMock.mockReset();
  completeUploadMock.mockReset();
  completeUploadMock.mockResolvedValue(completedAsset);
  messageError.mockReset();
  MockXMLHttpRequest.instances = [];
  vi.stubGlobal(
    "XMLHttpRequest",
    MockXMLHttpRequest as unknown as typeof XMLHttpRequest,
  );
  vi.stubGlobal("crypto", {
    subtle: {
      digest: vi.fn().mockResolvedValue(digestBytes.buffer),
    },
  });
  vi.spyOn(AntdApp, "useApp").mockReturnValue({
    message: { error: messageError },
  } as unknown as ReturnType<typeof AntdApp.useApp>);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FileUpload multipart POST", () => {
  it("reflects external controlled-value changes in the file list", async () => {
    const { container, rerender } = render(<FileUpload />);
    expect(container.textContent).not.toContain("new.png");

    rerender(
      <FileUpload value="https://cdn.example.test/uploads/news/new.png" />,
    );

    await waitFor(() => {
      expect(container.textContent).toContain("new.png");
    });
  });

  it("hashes the file, sends its declaration, and appends the file last", async () => {
    const uploadFields = {
      key: "uploads/news/signed-cover.png",
      policy: "signed-policy",
      "x-amz-meta-declared-sha256": checksumSha256,
    };
    uploadPresignMock.mockResolvedValue({
      upload_url: "https://storage.example.test/public",
      upload_method: "POST",
      upload_fields: uploadFields,
      object_key: "uploads/news/signed-cover.png",
      public_url: "https://cdn.example.test/uploads/news/signed-cover.png",
      expires_in: 3600,
    });
    const onChange = vi.fn();
    const { container } = render(<FileUpload onChange={onChange} />);
    const { file, arrayBuffer } = makeFile();

    chooseFile(container, file);

    await waitFor(() => {
      expect(uploadPresignMock).toHaveBeenCalledWith({
        filename: "cover.png",
        purpose: "news",
        size: 4,
        content_type: "image/png",
        checksum_sha256: checksumSha256,
      });
    });
    expect(arrayBuffer).toHaveBeenCalledOnce();
    expect(crypto.subtle.digest).toHaveBeenCalledWith(
      "SHA-256",
      expect.any(ArrayBuffer),
    );

    await waitFor(() => expect(MockXMLHttpRequest.instances).toHaveLength(1));
    const xhr = MockXMLHttpRequest.instances[0];
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("https://storage.example.test/public");
    expect(xhr.setRequestHeader).not.toHaveBeenCalled();
    expect(xhr.body).toBeInstanceOf(FormData);

    const entries = Array.from((xhr.body as FormData).entries());
    expect(entries.map(([name]) => name)).toEqual([
      ...Object.keys(uploadFields),
      "file",
    ]);
    expect(entries.slice(0, -1)).toEqual(Object.entries(uploadFields));
    expect(entries.at(-1)?.[1]).toBe(file);

    expect(xhr.upload.onprogress).toEqual(expect.any(Function));
    act(() => {
      xhr.upload.onprogress?.({
        lengthComputable: true,
        loaded: 2,
        total: 4,
      } as ProgressEvent);
      xhr.succeed();
    });

    await waitFor(() => {
      expect(completeUploadMock).toHaveBeenCalledWith({
        object_key: "uploads/news/signed-cover.png",
        filename: "cover.png",
        purpose: "news",
        size: 4,
        content_type: "image/png",
        checksum_sha256: checksumSha256,
      });
      expect(onChange).toHaveBeenCalledWith(
        "https://cdn.example.test/uploads/news/signed-cover.png",
      );
    });
  });

  it("rejects a presign response whose upload method is not POST", async () => {
    uploadPresignMock.mockResolvedValue({
      upload_url: "https://storage.example.test/public",
      upload_method: "PUT",
      upload_fields: {},
      object_key: "uploads/news/signed-cover.png",
      public_url: "https://cdn.example.test/uploads/news/signed-cover.png",
      expires_in: 3600,
    } as unknown as UploadPresignResponse);
    const onChange = vi.fn();
    const { container } = render(<FileUpload onChange={onChange} />);

    chooseFile(container, makeFile().file);

    await waitFor(() => {
      // The message is the rendered translation, not the raw i18n key.
      expect(messageError).toHaveBeenCalledWith(
        expect.stringContaining("Upload presign response must use POST"),
      );
    });
    expect(MockXMLHttpRequest.instances).toHaveLength(0);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("fails closed when the browser supplies an empty MIME type", async () => {
    const onChange = vi.fn();
    const { container } = render(<FileUpload onChange={onChange} />);
    const { file, arrayBuffer } = makeFile("");

    chooseFile(container, file);

    await waitFor(() => {
      // The message is the rendered translation, not the raw i18n key.
      expect(messageError).toHaveBeenCalledWith(
        expect.stringContaining("File MIME type is required"),
      );
    });
    expect(arrayBuffer).not.toHaveBeenCalled();
    expect(uploadPresignMock).not.toHaveBeenCalled();
    expect(MockXMLHttpRequest.instances).toHaveLength(0);
    expect(onChange).not.toHaveBeenCalled();
  });
});
