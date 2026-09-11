import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ModulePreviewResult } from "../lib/module-import-upload";
import ImportsPage from "./imports";

const { capabilitiesGetMock, fetchModulePreviewMock, httpGetMock } = vi.hoisted(() => ({
  capabilitiesGetMock: vi.fn(),
  fetchModulePreviewMock: vi.fn(),
  httpGetMock: vi.fn(),
}));

vi.mock("@soymutdb/api-client", () => ({
  capabilitiesApi: { get: capabilitiesGetMock },
  http: {
    get: httpGetMock,
    post: vi.fn(),
    delete: vi.fn(),
  },
  apiBaseUrl: "/api/v1",
  getAccessToken: vi.fn(() => null),
}));


vi.mock("../components/data-table", () => ({ DataTable: () => <div /> }));
vi.mock("../components/status-badge", () => ({ StatusBadge: () => <span /> }));
vi.mock("../components/import-preview-table", () => ({ ImportPreviewTable: () => <div /> }));
vi.mock("../lib/module-import-upload", () => ({
  uploadModuleFile: vi.fn(),
  fetchModulePreview: fetchModulePreviewMock,
}));

const availablePreview: ModulePreviewResult = {
  status: "available",
  headers: ["gene_id"],
  rows: [{ gene_id: "OLD" }],
  rowCount: 1,
  truncated: false,
  checksumSha256: "a".repeat(64),
  validation: { ok: true, errorCount: 0, errors: [] },
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ImportsPage />
    </QueryClientProvider>,
  );
}

function deferredPreview() {
  let resolve: (result: ModulePreviewResult) => void;
  const promise = new Promise<ModulePreviewResult>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve: (result: ModulePreviewResult) => resolve!(result) };
}

async function startModulePreview(
  user: ReturnType<typeof userEvent.setup>,
  container: HTMLElement,
  file: File,
) {
  await user.click(await screen.findByRole("button", { name: "New Import" }));
  const typeSelect = screen
    .getByRole("combobox", { name: "Import Type" });
  expect(typeSelect).toBeDefined();
  await user.click(typeSelect!);
  // antd renders the selected option's label both in the trigger and in the
    // open dropdown, so scope the click to the dropdown option.
    await user.click(await screen.findByRole("option", { name: "Module Data" }));

  const fileInput = document.body.querySelector<HTMLInputElement>('input[type="file"]');
  expect(fileInput).not.toBeNull();
  fireEvent.change(fileInput!, { target: { files: [file] } });
  await user.click(screen.getByRole("button", { name: "Preview" }));
}

beforeEach(() => {
  capabilitiesGetMock.mockReset();
  fetchModulePreviewMock.mockReset();
  httpGetMock.mockReset();
  capabilitiesGetMock.mockResolvedValue({
    features: {
      "imports.module_tsv": true,
      "imports.module_xlsx": true,
      "imports.local_upload": true,
    },
  });
  httpGetMock.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
});

describe("ImportsPage module preview request identity", () => {
  it("does not show an old preview after its module key changes", async () => {
    const pending = deferredPreview();
    fetchModulePreviewMock.mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    const { container } = renderPage();
    const file = new File(["gene_id\nG1\n"], "genes.tsv", { type: "text/tab-separated-values" });

    await startModulePreview(user, container, file);
    const moduleKeyInput = document.body.querySelector<HTMLInputElement>("#import-module-key");
    expect(moduleKeyInput).not.toBeNull();
    await user.clear(moduleKeyInput!);
    await user.type(moduleKeyInput!, "variants");

    await act(async () => {
      pending.resolve(availablePreview);
    });

    expect(screen.queryByText(/Validated 1 row/)).not.toBeInTheDocument();
  });

  it("does not show an old preview after its file changes", async () => {
    const pending = deferredPreview();
    fetchModulePreviewMock.mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    const { container } = renderPage();
    const firstFile = new File(["gene_id\nG1\n"], "genes.tsv", { type: "text/tab-separated-values" });
    const secondFile = new File(["gene_id\nG2\n"], "replacement.tsv", { type: "text/tab-separated-values" });

    await startModulePreview(user, container, firstFile);
    const fileInput = document.body.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput!, { target: { files: [secondFile] } });

    await act(async () => {
      pending.resolve(availablePreview);
    });

    expect(screen.queryByText(/Validated 1 row/)).not.toBeInTheDocument();
  });
});
