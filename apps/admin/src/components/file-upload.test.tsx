import * as React from "react";
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../lib/antd";

import FileUpload from "./file-upload";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);

/**
 * Test boundary
 *
 * Everything below the antd <Upload> is the real component: the real file
 * input, rc-upload's beforeUpload pipeline, the real picture list and its
 * real delete buttons. Files are selected through a real "change" event on
 * the rendered <input type="file"> and removals through a real click on
 * antd's own "Remove file" action button, so the assertions cover the wiring
 * that changed (onChange + status === "removed") instead of a hand-fed
 * UploadProps object.
 *
 * Doubled: only the network layer (uploadPresign/completeUpload) and
 * XMLHttpRequest, which jsdom cannot POST multipart bodies with. Message
 * assertions rely on the shared i18n double (t without defaultValue returns
 * the key), so the asserted text is a translation key, not English copy.
 */

const api = vi.hoisted(() => ({
  uploadPresign: vi.fn(),
  completeUpload: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    uploadPresign: api.uploadPresign,
    completeUpload: api.completeUpload,
  };
});

// The admin app compiles TSX with the classic React.createElement factory
// (tsconfig sets jsx: "preserve") and its component modules deliberately do
// not import React, so the identifier must exist globally before first render.
(globalThis as unknown as { React: unknown }).React = React;

const URL_ALPHA = "https://cdn.soymutdb.org/uploads/news/alpha.png";
const URL_BRAVO = "https://cdn.soymutdb.org/uploads/news/bravo.png";
const URL_CHARLIE = "https://cdn.soymutdb.org/uploads/news/charlie.png";

type Emitted = string | string[] | undefined;

interface ProgressEventLike {
  lengthComputable: boolean;
  loaded: number;
  total: number;
}

/** Minimal XMLHttpRequest stand-in: jsdom cannot POST a multipart body. */
class FakeXhr {
  static instances: FakeXhr[] = [];
  status = 0;
  upload: { onprogress: ((event: ProgressEventLike) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    FakeXhr.instances.push(this);
  }

  open() {}
  send() {}
  abort() {}
}

function ControlledFileUpload({
  initial,
  maxCount = 1,
  maxSizeMB = 1,
  onChange,
}: {
  initial?: string | string[];
  maxCount?: number;
  maxSizeMB?: number;
  onChange: (value: Emitted) => void;
}) {
  const [value, setValue] = React.useState<string | string[] | undefined>(initial);
  return (
    <App>
      <FileUpload
        value={value}
        maxCount={maxCount}
        maxSizeMB={maxSizeMB}
        onChange={(next) => {
          setValue(next);
          onChange(next);
        }}
      />
    </App>
  );
}

// A removed row stays mounted for its leave transition, and jsdom never fires
// the transition events that unmount it, so a row animating out is excluded
// from the current list instead of being counted.
function currentItems(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>(".ant-upload-list-item")).filter(
    (node) =>
      !node.closest(".ant-upload-list-item-container")?.className.includes("animate-leave"),
  );
}

function listItemNames(): string[] {
  return currentItems().map(
    (node) => node.querySelector(".ant-upload-list-item-name")?.textContent ?? "",
  );
}

/** The antd delete action of the list item whose file name is "name". */
function deleteButtonFor(name: string): HTMLElement {
  const item = currentItems().find(
    (node) => node.querySelector(".ant-upload-list-item-name")?.textContent === name,
  );
  if (!item) {
    throw new Error("no list item named " + name + "; have " + listItemNames().join(", "));
  }
  const button = item.querySelector<HTMLElement>("button[aria-label]");
  if (!button) throw new Error("no action button on list item " + name);
  return button;
}

function fileInput(): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("Upload input not rendered");
  return input;
}

function selectFile(file: File) {
  fireEvent.change(fileInput(), { target: { files: [file] } });
}

function pngFile(name: string, sizeBytes: number): File {
  return new File([new Uint8Array(sizeBytes)], name, { type: "image/png" });
}

beforeEach(() => {
  // AntD Upload's useDelayState schedules native timeouts without cancelling
  // them on unmount. Own the clock so no delayed React update can escape this
  // file and run after Vitest has removed its jsdom window.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  api.uploadPresign.mockReset();
  api.completeUpload.mockReset();
  FakeXhr.instances.length = 0;
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
});

afterEach(async () => {
  cleanup();
  try {
    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });
    expect(vi.getTimerCount()).toBe(0);
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});

describe("FileUpload removal path", () => {
  // antd routes a removal through onRemove -> Promise.resolve(...).then(...),
  // so every assertion here waits for the microtask that reaches onChange.
  it("drops exactly the removed URL from a multi-file list and keeps the rest", async () => {
    const onChange = vi.fn();
    render(
      <ControlledFileUpload
        initial={[URL_ALPHA, URL_BRAVO, URL_CHARLIE]}
        maxCount={3}
        onChange={onChange}
      />,
    );

    expect(listItemNames()).toEqual(["alpha.png", "bravo.png", "charlie.png"]);

    fireEvent.click(deleteButtonFor("bravo.png"));

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange).toHaveBeenCalledWith([URL_ALPHA, URL_CHARLIE]);
    await waitFor(() => expect(listItemNames()).toEqual(["alpha.png", "charlie.png"]));
  });

  it("emits undefined once the last entry of a multi-file list is removed", async () => {
    const onChange = vi.fn();
    render(
      <ControlledFileUpload initial={[URL_ALPHA, URL_BRAVO]} maxCount={3} onChange={onChange} />,
    );

    fireEvent.click(deleteButtonFor("bravo.png"));
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange).toHaveBeenLastCalledWith([URL_ALPHA]);
    await waitFor(() => expect(listItemNames()).toEqual(["alpha.png"]));

    fireEvent.click(deleteButtonFor("alpha.png"));
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2));
    expect(onChange).toHaveBeenCalledTimes(2);
    expect(onChange).toHaveBeenLastCalledWith(undefined);
    await waitFor(() => expect(listItemNames()).toEqual([]));
  });

  it("emits undefined when the single file is removed", async () => {
    const onChange = vi.fn();
    render(<ControlledFileUpload initial={URL_ALPHA} onChange={onChange} />);

    expect(listItemNames()).toEqual(["alpha.png"]);

    fireEvent.click(deleteButtonFor("alpha.png"));

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(undefined);
    await waitFor(() => expect(listItemNames()).toEqual([]));
  });
});

describe("FileUpload publishes a URL only after the upload completes", () => {
  it("stays silent across the uploading and progress events, then emits on success", async () => {
    const onChange = vi.fn();
    const published = "https://cdn.soymutdb.org/uploads/news/published.png";
    api.uploadPresign.mockResolvedValue({
      upload_url: "https://minio.internal/presigned",
      upload_method: "POST",
      upload_fields: { key: "uploads/news/published.png" },
      object_key: "uploads/news/published.png",
      public_url: published,
    });
    api.completeUpload.mockResolvedValue({
      asset_id: 7,
      object_key: "uploads/news/published.png",
      public_url: published,
    });

    render(<ControlledFileUpload onChange={onChange} />);
    selectFile(pngFile("published.png", 8));

    await waitFor(() => expect(api.uploadPresign).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(FakeXhr.instances).toHaveLength(1));

    // antd reports "uploading" once the file is queued and "done" on success.
    // Neither may publish a URL: only customRequest, after the server has
    // verified the object, is allowed to change the controlled value.
    // The in-flight entry itself never appears in the list: fileList is fully
    // controlled by the public URL, so only a published URL can render a row.
    expect(onChange).not.toHaveBeenCalled();
    expect(api.completeUpload).not.toHaveBeenCalled();
    expect(listItemNames()).toEqual([]);

    const xhr = FakeXhr.instances[0];
    expect(typeof xhr.upload.onprogress).toBe("function");
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 4, total: 8 });
    expect(onChange).not.toHaveBeenCalled();
    expect(listItemNames()).toEqual([]);

    xhr.status = 200;
    xhr.onload?.();

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange).toHaveBeenCalledWith(published);
    expect(api.completeUpload).toHaveBeenCalledTimes(1);
    expect(listItemNames()).toEqual(["published.png"]);
  });
});

describe("FileUpload size guard", () => {
  it("rejects an oversized file in beforeUpload without starting an upload", async () => {
    const onChange = vi.fn();
    render(<ControlledFileUpload maxSizeMB={1} onChange={onChange} />);

    selectFile(pngFile("oversized.png", 2 * 1024 * 1024));

    await waitFor(() =>
      expect(document.body.textContent).toContain("admin.uploads.sizeExceeded"),
    );
    expect(api.uploadPresign).not.toHaveBeenCalled();
    expect(api.completeUpload).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
    expect(listItemNames()).toEqual([]);
  });
});
