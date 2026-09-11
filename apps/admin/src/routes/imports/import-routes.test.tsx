import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ImportSubmitEntry } from "./import-submit-entry";
import { ImportTaskDetailPage } from "./task-detail";

const httpGetMock = vi.hoisted(() => vi.fn());

vi.mock("@soymutdb/api-client", () => ({ http: { get: httpGetMock } }));
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, ...props }: { children: React.ReactNode }) => <a {...props}>{children}</a>,
  useParams: () => ({ taskId: "1" }),
}));
vi.mock("@/lib/antd", () => ({
  Button: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
  Typography: { Title: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2> },
}));
vi.mock("../imports", () => ({
  default: ({ initialUploadOpen }: { initialUploadOpen?: boolean }) => (
    <div data-testid="legacy-import-submit" data-open={String(initialUploadOpen)} />
  ),
}));

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("incremental import routes", () => {
  it("opens the validated legacy submit flow for /imports/new", () => {
    renderWithQuery(<ImportSubmitEntry />);
    expect(screen.getByTestId("legacy-import-submit")).toHaveAttribute("data-open", "true");
  });

  it("renders a task detail loaded from the task route API", async () => {
    httpGetMock.mockResolvedValueOnce({
      id: 17, filename: "genes.tsv", type: "module_tsv", status: "completed",
      progress: 100, processed_records: 20, total_records: 20, error_message: null,
      submitted_at: "2026-01-01", completed_at: "2026-01-02",
    });
    renderWithQuery(<ImportTaskDetailPage taskId={17} />);
    await waitFor(() => expect(httpGetMock).toHaveBeenCalledWith("/admin/imports/17"));
    expect(await screen.findByText("Import task #17")).toBeInTheDocument();
    expect(screen.getByText("genes.tsv")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
  });
});
