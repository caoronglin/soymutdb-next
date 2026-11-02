/**
 * Audit-log console contract.
 *
 * A compliance screen must never turn a transport failure into "nothing
 * happened". The list query and the statistics query used to have no
 * `isError` branch: the page fell back to `data?.items ?? []` and rendered
 * "No audit records" together with zeroed stat cards, so a failed request was
 * indistinguishable from an empty log.
 */
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => {
  const double = await import("../test/antd-double");
  return {
    ...double,
    /**
     * The shared double renders the pagination as a static marker, so a test
     * cannot move the operator off page 1. This control reports the page the
     * double cannot show: a filter change has to answer with page 1, and that
     * answer only means something after the operator has paged away.
     */
    Pagination: (props: { current?: number; onChange?: (page: number) => void }) => (
      <button
        type="button"
        data-testid="pagination-page-3"
        onClick={() => props.onChange?.(3)}
      >
        {String(props.current ?? "")}
      </button>
    ),
  };
});

const api = vi.hoisted(() => ({
  get: vi.fn(),
  download: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    http: {
      ...actual.http,
      get: api.get,
      download: api.download,
    },
  };
});

const AuditPage = (await import("./audit")).default;

beforeEach(() => {
  api.get.mockReset().mockRejectedValue(new Error("audit backend unreachable"));
  api.download.mockReset().mockRejectedValue(new Error("export failed"));
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuditPage />
    </QueryClientProvider>,
  );
}

describe("audit log error handling", () => {
  it("keeps pending requests unknown rather than showing empty records and zeros", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    renderPage();
    expect(screen.queryByText(/No audit records/)).toBeNull();
    expect(screen.queryByText(/No IP distribution data/)).toBeNull();
    expect(screen.getAllByTestId("statistic-value").map((node) => node.textContent)).toEqual(["—", "—", "—", "—"]);
    expect(screen.queryByText("0 records")).toBeNull();
  });

  it("still shows a genuine empty response as empty, with zero statistics", async () => {
    api.get.mockImplementation((url: string) => Promise.resolve(url.endsWith("/stats")
      ? { totalLogins: 0, totalActions: 0, uniqueIps: 0, ipDistribution: [] }
      : { items: [], total: 0 }));
    renderPage();
    expect(await screen.findByText(/No audit records/)).toBeInTheDocument();
    expect(screen.getAllByTestId("statistic-value").map((node) => node.textContent)).toEqual(["0", "0", "0", "0"]);
    expect(screen.queryByTestId("audit-load-error")).toBeNull();
  });
  it("renders an explicit error state instead of the empty audit log", async () => {
    renderPage();

    const alert = await screen.findByTestId("audit-load-error");
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent("The audit log could not be loaded.");

    // The empty state must not claim that nothing happened.
    expect(screen.queryByText(/No audit records/)).toBeNull();
  });

  it("does not render zeroed statistics when the statistics request failed", async () => {
    renderPage();

    const alert = await screen.findByTestId("audit-stats-error");
    expect(alert).toHaveTextContent("Audit statistics could not be loaded.");
    expect(screen.queryByText(/No IP distribution data/)).toBeNull();

    // The stat cards show an unknown value, not a hard zero.
    await waitFor(() =>
      expect(screen.getAllByTestId("statistic-value").some((node) => node.textContent === "0")).toBe(false),
    );
  });

  it("reports a failed CSV export instead of rejecting silently", async () => {
    renderPage();

    const exportButton = await screen.findByRole("button", { name: /Export CSV/ });
    fireEvent.click(exportButton);

    const error = await screen.findByTestId("audit-export-error");
    expect(error).toHaveTextContent("The CSV export failed.");
    expect(error).toHaveTextContent("export failed");
  });
});

/** One audit row as the list endpoint returns it. */
function auditRow(id: string) {
  return {
    id,
    timestamp: "2026-10-24T10:00:00Z",
    actor: "admin",
    action: "login",
    resource: "session",
    resourceId: id,
    ipAddress: "127.0.0.1",
    userAgent: "vitest",
    status: "success" as const,
    details: null,
  };
}

describe("audit log pagination", () => {
  it("asks for page 1 again when a filter changes after the operator paged away", async () => {
    const listRequests: Array<Record<string, unknown>> = [];
    api.get.mockImplementation(
      (url: string, options?: { params?: Record<string, unknown> }) => {
        if (url.endsWith("/stats")) {
          return Promise.resolve({
            totalLogins: 3,
            totalActions: 9,
            uniqueIps: 2,
            ipDistribution: [],
          });
        }
        listRequests.push(options?.params ?? {});
        // 150 records over a 50-row page: page 3 exists, so the page number
        // under test is a real page of the unfiltered result set.
        return Promise.resolve({ items: [auditRow("row-1")], total: 150 });
      },
    );

    renderPage();

    await waitFor(() => expect(listRequests.length).toBe(1));
    expect(listRequests[0]).toMatchObject({ page: 1 });

    // The operator moves to page 3 ...
    fireEvent.click(await screen.findByTestId("pagination-page-3"));
    await waitFor(() => expect(listRequests.length).toBe(2));
    expect(listRequests[1]).toMatchObject({ page: 3 });

    // ... and then narrows the result set.
    fireEvent.change(screen.getByPlaceholderText(/Search by actor, resource, or IP/), {
      target: { value: "alice" },
    });

    await waitFor(() => expect(listRequests.length).toBe(3));
    // The narrowed request asks for page 1: the previous page number belongs
    // to the previous filter scope, not to the filtered one.
    expect(listRequests[2]).toMatchObject({ page: 1, search: "alice" });
    // No request may carry the new filter together with the stale page
    // number. That request is what makes the compliance screen claim "no
    // audit records" for a page the filtered result set never had.
    expect(
      listRequests.filter((request) => request.search === "alice" && request.page !== 1),
    ).toEqual([]);
    expect(listRequests.map((request) => request.page)).toEqual([1, 3, 1]);
  });
});
