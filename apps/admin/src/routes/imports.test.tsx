/**
 * Import-task console contract.
 *
 * Cancelling a task used a native `window.confirm("Cancel this import task?")`
 * — an unstyled English prompt inside a Chinese console — and neither the
 * cancel nor the retry mutation reported a failure, so a rejected write left
 * the operator with no signal at all.
 */
import * as React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));

vi.mock("@tanstack/react-router", () => ({
  Link: (props: { children?: React.ReactNode; to?: string; params?: Record<string, string> }) => (
    <a href="#/imports">{props.children}</a>
  ),
}));

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
  download: vi.fn(),
  authRequestBlob: vi.fn(),
  capabilitiesGet: vi.fn(),
  listDrafts: vi.fn(),
  getDraft: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    http: {
      ...actual.http,
      get: api.get,
      post: api.post,
      delete: api.delete,
      download: api.download,
    },
    authRequestBlob: api.authRequestBlob,
    capabilitiesApi: { ...actual.capabilitiesApi, get: api.capabilitiesGet },
    adminImportStudioApi: {
      ...actual.adminImportStudioApi,
      listDrafts: api.listDrafts,
      getDraft: api.getDraft,
    },
  };
});

const ImportsPage = (await import("./imports")).default;

const RUNNING_TASK = {
  id: 1,
  filename: "genes.tsv",
  type: "module_tsv",
  status: "running",
  progress: 10,
  total_records: 100,
  processed_records: 10,
  celery_task_id: "celery-1",
  submitted_by: "admin",
  file_path: "s3://bucket/genes.tsv",
  error_message: null,
  submitted_at: "2026-01-01T00:00:00Z",
  completed_at: null,
};

const FAILED_TASK = {
  ...RUNNING_TASK,
  id: 2,
  filename: "broken.tsv",
  status: "failed",
  progress: 0,
  processed_records: 0,
  error_message: "row 3: unknown column",
};

beforeEach(() => {
  api.get.mockReset().mockImplementation((url: string) => {
    if (url === "/admin/imports") {
      return Promise.resolve({ items: [RUNNING_TASK, FAILED_TASK], total: 2, page: 1, page_size: 20 });
    }
    return Promise.reject(new Error("unstubbed GET " + url));
  });
  api.post.mockReset().mockRejectedValue(new Error("retry rejected"));
  api.delete.mockReset().mockRejectedValue(new Error("cancel rejected"));
  api.capabilitiesGet.mockReset().mockResolvedValue({
    version: 1,
    features: {
      "imports.module_tsv": true,
      "imports.module_xlsx": true,
      "imports.local_upload": true,
    },
    plugins: {},
    databases: { authoritative: "postgresql", analytics: null },
  });
  api.listDrafts.mockReset().mockResolvedValue([]);
  api.getDraft.mockReset().mockRejectedValue(new Error("no draft"));
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ImportsPage />
    </QueryClientProvider>,
  );
}

describe("import task cancel and retry", () => {
  it("does not claim no tasks while pending or after a list failure", async () => {
    let rejectRequest!: (error: Error) => void;
    api.get.mockImplementation(() => new Promise((_resolve, reject) => { rejectRequest = reject; }));
    renderPage();
    expect(screen.getByTestId("imports-table")).toHaveAttribute("data-state", "loading");
    expect(screen.queryByText(/No import tasks/)).toBeNull();
    expect(screen.getAllByTestId("statistic-value").map((node) => node.textContent)).toEqual(["—", "—", "—", "—"]);
    rejectRequest(new Error("imports unavailable"));
    expect(await screen.findByTestId("imports-load-error")).toHaveAttribute("role", "alert");
    expect(screen.queryByText(/No import tasks/)).toBeNull();
    expect(screen.getAllByTestId("statistic-value").map((node) => node.textContent)).toEqual(["—", "—", "—", "—"]);
  });
  it("does not claim no saved drafts after their request failed", async () => {
    api.listDrafts.mockRejectedValue(new Error("drafts unavailable"));
    renderPage();
    expect(await screen.findByText("admin.importPage.savedDraftsUnavailable")).toBeInTheDocument();
    expect(screen.queryByText("admin.importPage.noDrafts")).toBeNull();
  });

  it("confirms a cancel in the shared dialog and never calls window.confirm", async () => {
    const nativeConfirm = vi.spyOn(window, "confirm");
    renderPage();

    const cancel = await screen.findByTestId("imports-cancel-task");
    fireEvent.click(cancel);

    expect(nativeConfirm).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(api.delete).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel task" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/admin/imports/1"));
  });

  it("reports a rejected cancel inside the confirmation dialog", async () => {
    renderPage();

    const cancel = await screen.findByTestId("imports-cancel-task");
    fireEvent.click(cancel);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel task" }));

    const error = await screen.findByTestId("imports-cancel-error");
    expect(error.closest('[role="alert"]')).not.toBeNull();
    expect(error).toHaveTextContent("could not be cancelled");
    expect(error).toHaveTextContent("cancel rejected");
  });

  it("confirms a retry and reports a rejected retry", async () => {
    const nativeConfirm = vi.spyOn(window, "confirm");
    renderPage();

    const retry = await screen.findByTestId("imports-retry-task");
    fireEvent.click(retry);

    expect(nativeConfirm).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/admin/imports/2/retry"));

    const error = await screen.findByTestId("imports-retry-error");
    expect(error.closest('[role="alert"]')).not.toBeNull();
    expect(error).toHaveTextContent("could not be retried");
    expect(error).toHaveTextContent("retry rejected");
  });
});
