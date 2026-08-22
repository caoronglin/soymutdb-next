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

vi.mock("../lib/admin-ui", () => ({
  cn: (...values: Array<string | false | null | undefined>) => values.filter(Boolean).join(" "),
  Button: ({ children, type = "button", ...props }: React.ComponentProps<"button">) => (
    <button type={type} {...props}>{children}</button>
  ),
  Input: (props: React.ComponentProps<"input">) => <input {...props} />,
  Label: (props: React.ComponentProps<"label">) => <label {...props} />,
  Badge: ({ children }: { children?: React.ReactNode }) => <span>{children}</span>,
  Dialog: ({ open, children }: { open: boolean; children: React.ReactNode }) => open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PageHeader: ({ actions }: { actions?: React.ReactNode }) => <header>{actions}</header>,
  Select: ({ value, onValueChange, children }: { value?: string; onValueChange?: (value: string) => void; children: React.ReactNode }) => (
    <select value={value} onChange={(event) => onValueChange?.(event.target.value)}>{children}</select>
  ),
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ value, disabled, children }: { value: string; disabled?: boolean; children: React.ReactNode }) => (
    <option value={value} disabled={disabled}>{children}</option>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  StatCard: () => <div />,
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
    const moduleTypeSelect = screen
      .getAllByRole("combobox")
      .find((select) => select.textContent?.includes("Module Data"));
    expect(moduleTypeSelect).toBeDefined();
    await user.selectOptions(moduleTypeSelect!, "module_tsv");

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
