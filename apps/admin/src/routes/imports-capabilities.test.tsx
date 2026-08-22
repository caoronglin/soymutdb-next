import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ImportsPage from "./imports";

const { capabilitiesGetMock, httpGetMock } = vi.hoisted(() => ({
  capabilitiesGetMock: vi.fn(),
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

vi.mock("../components/data-table", () => ({
  DataTable: () => <div>imports table</div>,
}));

vi.mock("../components/status-badge", () => ({ StatusBadge: () => <span /> }));
vi.mock("../lib/auth-context", () => ({
  useAuth: () => ({ user: { email: "admin@example.test" } }),
}));
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
  httpGetMock.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
});

describe("ImportsPage capability gate", () => {
  it("keeps the import entry unavailable while its capability snapshot loads", () => {
    capabilitiesGetMock.mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(screen.getByText("Loading import capabilities…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New Import" })).toBeDisabled();
  });

  it("reports a capability request failure instead of calling imports disabled", async () => {
    capabilitiesGetMock.mockRejectedValue(new Error("offline"));
    renderPage();

    expect(await screen.findByRole("alert", { name: "Import capabilities unavailable" })).toHaveTextContent(
      "Unable to load import capabilities.",
    );
    expect(screen.queryByText("Module imports are disabled.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New Import" })).toBeDisabled();
  });
});
