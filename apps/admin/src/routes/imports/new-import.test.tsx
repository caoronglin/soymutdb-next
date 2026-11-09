import * as React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { http } from "@soymutdb/api-client";
import { uploadModuleFile } from "../../lib/module-import-upload";
import { createQueryClient } from "../../lib/query-client";

import NewImportPage from "./new";

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../../test/antd-double")));

// `capabilitiesApi` closes over the module's own `http` binding, so the shared
// facade is doubled explicitly; everything else in the client stays real.
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
    capabilitiesApi: {
      ...actual.capabilitiesApi,
      get: vi.fn(() => Promise.resolve(doubles.capabilities)),
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
const uploadModuleFileMock = vi.mocked(uploadModuleFile);

// The admin app compiles TSX with the classic `React.createElement` factory
// (tsconfig sets `jsx: "preserve"`) and its component modules deliberately do
// not import React. Binding the identifier as a global before the first render
// lets the real page mount under vitest.
(globalThis as unknown as { React: unknown }).React = React;

beforeEach(() => {
  post.mockReset();
  doubles.httpGet.mockReset();
  uploadModuleFileMock.mockReset();
});

function submitStub(overrides: { submit?: () => Promise<unknown> } = {}) {
  post.mockImplementation(((url: string) => {
    if (url === "/admin/imports") {
      return overrides.submit ? overrides.submit() : Promise.resolve({ id: 1 });
    }
    return Promise.reject(new Error("unstubbed POST " + url));
  }) as unknown as typeof http.post);
}

function renderWizard() {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <NewImportPage />
    </QueryClientProvider>,
  );
}

function tsvFile(name: string, bytes = 64): File {
  return new File([new Uint8Array(bytes)], name, { type: "text/tab-separated-values" });
}

function clickNext() {
  fireEvent.click(screen.getByTestId("import-wizard-next"));
}

async function waitForNextEnabled() {
  await waitFor(() =>
    expect(screen.getByTestId("import-wizard-next")).not.toBeDisabled(),
  );
}

async function chooseFile(file: File) {
  const input = await waitFor(() => {
    const found = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(found).not.toBeNull();
    return found!;
  });
  await act(async () => {
    fireEvent.change(input, { target: { files: [file] } });
  });
}

/** Reach the review step with a release ID and a selected local file. */
async function fillAndReachReview(file = tsvFile("genes.tsv")) {
  await waitForNextEnabled();
  const releaseInput = screen.getByLabelText("admin.importPage.releaseId");
  fireEvent.change(releaseInput, { target: { value: "7" } });
  clickNext();

  await chooseFile(file);
  clickNext();
  await screen.findByTestId("import-wizard-step-inspect");
  clickNext();
  await screen.findByTestId("import-wizard-step-review");
}

const submittedBodies = () =>
  post.mock.calls
    .filter((call) => call[0] === "/admin/imports")
    .map((call) => (call[1] as { json: { idempotency_key: string; filename: string } }).json);

describe("new import wizard", () => {
  it("starts one upload for two clicks in the same tick", async () => {
    submitStub();
    uploadModuleFileMock.mockResolvedValue({
      object_key: "data/1/genes.tsv",
      sha256: "a".repeat(64),
    });
    renderWizard();
    await fillAndReachReview();

    await act(async () => {
      // React has not re-rendered between these clicks, so a disabled state
      // driven by `uploading` / `isPending` cannot keep the second one out.
      fireEvent.click(screen.getByTestId("import-wizard-submit"));
      fireEvent.click(screen.getByTestId("import-wizard-submit"));
    });

    await waitFor(() => expect(uploadModuleFileMock).toHaveBeenCalledTimes(1));
    expect(submittedBodies()).toHaveLength(1);
    await screen.findByTestId("import-submitted");
  });

  it("retries a failed submission without uploading the same file again", async () => {
    submitStub({ submit: () => Promise.reject(new Error("boom")) });
    uploadModuleFileMock.mockResolvedValue({
      object_key: "data/1/genes.tsv",
      sha256: "a".repeat(64),
    });
    renderWizard();
    await fillAndReachReview();

    fireEvent.click(screen.getByTestId("import-wizard-submit"));
    await screen.findByText(/boom/);

    await act(async () => {
      fireEvent.click(screen.getByTestId("import-wizard-submit"));
    });

    // Same intent: the finished object is reused and the same key is replayed,
    // so the API answers with the task it already created.
    expect(uploadModuleFileMock).toHaveBeenCalledTimes(1);
    const bodies = submittedBodies();
    expect(bodies).toHaveLength(2);
    expect(bodies[1].idempotency_key).toBe(bodies[0].idempotency_key);
  });

  it("rotates the idempotency key when the operator changes the file after a failure", async () => {
    submitStub({ submit: () => Promise.reject(new Error("boom")) });
    uploadModuleFileMock.mockResolvedValue({
      object_key: "data/1/genes.tsv",
      sha256: "a".repeat(64),
    });
    renderWizard();
    await fillAndReachReview();

    fireEvent.click(screen.getByTestId("import-wizard-submit"));
    await screen.findByText(/boom/);

    fireEvent.click(screen.getByTestId("import-wizard-back"));
    fireEvent.click(screen.getByTestId("import-wizard-back"));
    await chooseFile(tsvFile("other.tsv", 32));
    clickNext();
    clickNext();
    await screen.findByTestId("import-wizard-step-review");

    await act(async () => {
      fireEvent.click(screen.getByTestId("import-wizard-submit"));
    });

    // Replaying the old key would make the API return the first task and drop
    // the new file without an error.
    const bodies = submittedBodies();
    expect(bodies).toHaveLength(2);
    expect(bodies[1].idempotency_key).not.toBe(bodies[0].idempotency_key);
    expect(uploadModuleFileMock).toHaveBeenCalledTimes(2);
  });

  it("drops the selected file when the operator starts over", async () => {
    submitStub();
    renderWizard();
    await waitForNextEnabled();
    fireEvent.change(screen.getByLabelText("admin.importPage.releaseId"), {
      target: { value: "7" },
    });
    clickNext();
    await chooseFile(tsvFile("genes.tsv"));
    expect((await screen.findAllByText(/genes\.tsv/)).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByTestId("import-wizard-start-over"));

    await screen.findByTestId("import-wizard-step-source");
    expect(screen.queryAllByText(/genes\.tsv/)).toHaveLength(0);
  });
});