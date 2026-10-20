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
vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));

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
