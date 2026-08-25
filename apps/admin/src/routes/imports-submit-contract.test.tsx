import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ImportsPage from "./imports";

const { capabilitiesGetMock, httpGetMock, httpPostMock } = vi.hoisted(() => ({
  capabilitiesGetMock: vi.fn(),
  httpGetMock: vi.fn(),
  httpPostMock: vi.fn(),
}));

vi.mock("@soymutdb/api-client", () => ({
  capabilitiesApi: { get: capabilitiesGetMock },
  http: {
    get: httpGetMock,
    post: httpPostMock,
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
  fetchModulePreview: vi.fn(),
}));

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

beforeEach(() => {
  capabilitiesGetMock.mockReset();
  httpGetMock.mockReset();
  httpPostMock.mockReset();
  capabilitiesGetMock.mockResolvedValue({
    features: {
      "imports.module_tsv": true,
      "imports.module_xlsx": true,
      "imports.local_upload": false,
    },
  });
  httpGetMock.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
  httpPostMock.mockResolvedValue({ id: 1 });
});

describe("ImportsPage module submit contract", () => {
  it("sends the entered release id and an idempotency key to the API", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "New Import" }));
    const moduleTypeSelect = screen.getByRole("combobox", { name: "Import Type" });
    await user.click(moduleTypeSelect);
    await user.click(await screen.findByText("Module Data"));

    await user.type(screen.getByLabelText("Filename"), "genes.tsv");
    await user.type(screen.getByLabelText("S3 File Path"), "s3://archive/genes.tsv");
    await user.clear(screen.getByLabelText("Data Set ID"));
    await user.type(screen.getByLabelText("Data Set ID"), "17");
    await user.type(screen.getByLabelText("Release ID"), "42");
    await user.type(screen.getByLabelText("Checksum"), "a".repeat(64));
    await user.click(screen.getByRole("button", { name: "Submit Import" }));

    await waitFor(() => {
      expect(httpPostMock).toHaveBeenCalledWith(
        "/admin/imports",
        expect.objectContaining({
          json: expect.objectContaining({
            filename: "genes.tsv",
            type: "module_tsv",
            file_path: "s3://archive/genes.tsv",
            module_key: "genes",
            checksum: "a".repeat(64),
            data_set_id: 17,
            release_id: 42,
            idempotency_key: expect.stringMatching(/^import-/),
          }),
        }),
      );
    });
  });
});
