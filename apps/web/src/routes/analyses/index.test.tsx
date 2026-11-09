// @vitest-environment jsdom
import * as React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Route } from "./index";

/**
 * The analyses list used to fall back to a localStorage job-id cache whenever
 * the server list was empty or failed. On a shared browser that cache belongs
 * to whoever used it last, and it also hid backend errors behind stale rows.
 * These cases pin the contract that `GET /analyses` is the only source and
 * that its failures surface as an error state.
 */

const runtime = vi.hoisted(() => ({
  get: vi.fn(),
  useQueryOptions: null as null | { queryKey: unknown[]; queryFn: () => Promise<unknown> },
  queryState: {
    data: [] as unknown[],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  },
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({ options }),
  useNavigate: () => vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: { queryKey: unknown[]; queryFn: () => Promise<unknown> }) => {
    runtime.useQueryOptions = options;
    return runtime.queryState;
  },
}));
vi.mock("../../lib/api", () => ({
  secureHttp: { get: (...args: unknown[]) => runtime.get(...args) },
}));
vi.mock("../../components/analyses/researcher-gate", () => ({
  ResearcherGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("../../components/data-table", () => ({
  DataTable: ({ data }: { data: unknown[] }) => (
    <div data-testid="analysis-rows">{data.length}</div>
  ),
}));
vi.mock("@/lib/antd", () => ({
  Breadcrumb: () => <nav />,
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
  Result: ({ title }: { title?: React.ReactNode }) => (
    <div role="alert">{title}</div>
  ),
  Skeleton: () => null,
  Tag: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  Typography: {
    Title: ({ children }: { children: React.ReactNode }) => <h1>{children}</h1>,
    Paragraph: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  },
}));

const Page = (Route as unknown as { options: { component: React.ComponentType } }).options
  .component;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  runtime.queryState = { data: [], isLoading: false, isError: false, refetch: vi.fn() };
  runtime.useQueryOptions = null;
});

afterEach(() => {
  cleanup();
});

it("uses the server list as the only source when the response is empty", async () => {
  localStorage.setItem(
    "soymutdb.analyses.recent_jobs",
    JSON.stringify(["local-job-from-another-account"]),
  );
  runtime.get.mockResolvedValue({ items: [] });

  render(<Page />);

  const options = runtime.useQueryOptions;
  expect(options).not.toBeNull();
  await expect(options!.queryFn()).resolves.toEqual([]);
  expect(runtime.get).toHaveBeenCalledTimes(1);
  expect(runtime.get).toHaveBeenCalledWith("/analyses", { params: { limit: 50 } });
  expect(screen.getByTestId("analysis-rows").textContent).toBe("0");
});

it("returns the server rows without touching the local job cache", async () => {
  const rows = [
    { job_id: "job-1", analysis_type: "fastp", status: "succeeded", created_at: "2026-01-01" },
  ];
  runtime.get.mockResolvedValue({ items: rows });

  render(<Page />);

  await expect(runtime.useQueryOptions!.queryFn()).resolves.toEqual(rows);
  expect(runtime.get).toHaveBeenCalledTimes(1);
});

it("surfaces server failures instead of substituting stale local jobs", async () => {
  localStorage.setItem("soymutdb.analyses.recent_jobs", JSON.stringify(["local-job"]));
  runtime.get.mockRejectedValue(new Error("403"));
  runtime.queryState = {
    data: undefined,
    isLoading: false,
    isError: true,
    refetch: vi.fn(),
  };

  render(<Page />);

  expect(screen.getByRole("alert").textContent).toBe("analyses.jobsErrorTitle");
  await expect(runtime.useQueryOptions!.queryFn()).rejects.toThrow("403");
});