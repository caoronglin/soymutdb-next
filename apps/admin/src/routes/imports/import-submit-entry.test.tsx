import * as React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { http } from "@soymutdb/api-client";
import { uploadModuleFile } from "../../lib/module-import-upload";
import { createQueryClient } from "../../lib/query-client";

import { ImportSubmitEntry } from "./import-submit-entry";

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

// `capabilitiesApi` and `adminImportStudioApi` close over the module's own
// `http` binding, so replacing the `http` export alone leaves them on the real
// transport (the dialog then renders in S3 mode). Each surface the page calls is
// doubled explicitly, everything else stays real.
const doubles = vi.hoisted(() => ({
  httpGet: vi.fn(),
  httpPost: vi.fn(),
  httpDelete: vi.fn(),
  capabilities: {
    features: {
      "imports.module_tsv": true,
      "imports.module_xlsx": true,
      "imports.local_upload": true,
    },
  },
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    http: {
      ...actual.http,
      get: doubles.httpGet,
      post: doubles.httpPost,
      delete: doubles.httpDelete,
    },
    capabilitiesApi: { ...actual.capabilitiesApi, get: vi.fn(() => Promise.resolve(doubles.capabilities)) },
    adminImportStudioApi: {
      ...actual.adminImportStudioApi,
      listDrafts: vi.fn(() => Promise.resolve([])),
      getDraft: vi.fn(() => Promise.reject(new Error("no draft in this test"))),
    },
  };
});

// The transfer is doubled; describeUploadSource stays real because the page's
// reuse decision is built on it.
vi.mock("../../lib/module-import-upload", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/module-import-upload")>()),
  uploadModuleFile: vi.fn(),
}));

const post = doubles.httpPost;
const get = doubles.httpGet;
const uploadModuleFileMock = vi.mocked(uploadModuleFile);

// The admin app compiles TSX with the classic `React.createElement` factory
// (tsconfig sets `jsx: "preserve"`) and its component modules deliberately do
// not import React. Binding the identifier as a global before the first render
// lets the real page mount under vitest without editing app sources or the
// shared vitest config.
(globalThis as unknown as { React: unknown }).React = React;

beforeEach(() => {
  post.mockReset();
  get.mockReset();
  uploadModuleFileMock.mockReset();
  get.mockImplementation(((url: string) => {
    if (url === "/admin/imports") {
      return Promise.resolve({ items: [], total: 0, page: 1, page_size: 20 });
    }
    return Promise.reject(new Error("unstubbed GET " + url));
  }) as unknown as typeof http.get);
});

afterEach(() => {
  cleanup();
});

function submitStub(overrides: { submit?: () => Promise<unknown> } = {}) {
  post.mockImplementation(((url: string) => {
    if (url === "/admin/imports") {
      return overrides.submit ? overrides.submit() : Promise.resolve({ id: 1 });
    }
    return Promise.reject(new Error("unstubbed POST " + url));
  }) as unknown as typeof http.post);
}

function renderDialog() {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ImportSubmitEntry />
    </QueryClientProvider>,
  );
}

function tsvFile(name: string, bytes = 64): File {
  return new File([new Uint8Array(bytes)], name, { type: "text/tab-separated-values" });
}

async function chooseFile(file: File) {
  // The dialog mounts its local-file input once the capabilities query resolves.
  await waitFor(() =>
    expect(document.querySelector('input[type="file"]')).not.toBeNull(),
  );
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  await act(async () => {
    fireEvent.change(input, { target: { files: [file] } });
  });
}

async function fillModuleDraft(file = tsvFile("genes.tsv")) {
  await chooseFile(file);
  const releaseInput = await screen.findByLabelText("admin.importPage.releaseId");
  await act(async () => {
    fireEvent.change(releaseInput, { target: { value: "7" } });
  });
  return file;
}

async function clickSubmit() {
  const button = await screen.findByRole("button", { name: "Submit Import" });
  await act(async () => {
    fireEvent.click(button);
  });
}

const submittedBodies = () =>
  post.mock.calls
    .filter((call) => call[0] === "/admin/imports")
    .map((call) => (call[1] as { json: { idempotency_key: string; filename: string } }).json);

describe("import submission dialog", () => {
  // The assertions below are synchronous invariants (a second click in the same
  // tick must not start a second upload), but reaching them mounts the real
  // dialog: the capabilities query, the antd Modal and the import table. In CI
  // that filesystem-and-contention cost, not the behaviour under test, is what
  // decides whether 5s is enough. Give all four cases room so a busy box cannot
  // be reported as a defect; keep the hook budget alone, so a hung module still
  // fails fast.
  const CASE_TIMEOUT_MS = 30_000;

  it("starts one upload for two clicks in the same tick", async () => {
    submitStub();
    uploadModuleFileMock.mockResolvedValue({ object_key: "data/1/genes.tsv", sha256: "a".repeat(64) });
    renderDialog();
    await fillModuleDraft();

    const button = await screen.findByRole("button", { name: "Submit Import" });
    await act(async () => {
      // React has not re-rendered between these clicks, so a disabled state
      // driven by `uploading` / `isPending` cannot keep the second one out.
      fireEvent.click(button);
      fireEvent.click(button);
    });

    await waitFor(() => expect(uploadModuleFileMock).toHaveBeenCalledTimes(1));
    expect(submittedBodies()).toHaveLength(1);
  }, CASE_TIMEOUT_MS);

  it("retries a failed submission without uploading the same file again", async () => {
    submitStub({ submit: () => Promise.reject(new Error("boom")) });
    uploadModuleFileMock.mockResolvedValue({ object_key: "data/1/genes.tsv", sha256: "a".repeat(64) });
    renderDialog();
    await fillModuleDraft();
    await clickSubmit();
    await screen.findByText("boom");

    await clickSubmit();

    // Same intent: the finished object is reused and the same key is replayed,
    // so the API answers with the task it already created.
    expect(uploadModuleFileMock).toHaveBeenCalledTimes(1);
    const bodies = submittedBodies();
    expect(bodies).toHaveLength(2);
    expect(bodies[1].idempotency_key).toBe(bodies[0].idempotency_key);
  }, CASE_TIMEOUT_MS);

  it("rotates the idempotency key when the operator changes the file after a failure", async () => {
    submitStub({ submit: () => Promise.reject(new Error("boom")) });
    uploadModuleFileMock.mockResolvedValue({ object_key: "data/1/genes.tsv", sha256: "a".repeat(64) });
    renderDialog();
    await fillModuleDraft();
    await clickSubmit();
    await screen.findByText("boom");

    await chooseFile(tsvFile("other.tsv", 32));
    await clickSubmit();

    // Replaying the old key would make the API return the first task and drop
    // the new file without an error.
    const bodies = submittedBodies();
    expect(bodies).toHaveLength(2);
    expect(bodies[1].idempotency_key).not.toBe(bodies[0].idempotency_key);
    expect(uploadModuleFileMock).toHaveBeenCalledTimes(2);
  }, CASE_TIMEOUT_MS);

  it("does not carry a previously chosen file into a new dialog session", async () => {
    submitStub();
    renderDialog();
    await fillModuleDraft();
    expect((await screen.findAllByText(/genes\.tsv/)).length).toBeGreaterThan(0);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "admin.importPage.newImport" }));
    });

    await waitFor(() => expect(screen.getByText("Choose a local file")).toBeInTheDocument());
    expect(screen.queryAllByText(/genes\.tsv/)).toHaveLength(0);
  }, CASE_TIMEOUT_MS);
});
