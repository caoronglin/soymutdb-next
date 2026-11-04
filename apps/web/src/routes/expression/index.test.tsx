// @vitest-environment jsdom
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExpressionLibraryPage } from "@soymutdb/api-client";

const runtime = vi.hoisted(() => ({
  search: { page: 1, tissue: "", treatment: "", assembly: "" } as Record<string, unknown>,
  navigate: vi.fn(),
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useSearch: () => runtime.search,
    useNavigate: () => runtime.navigate,
  }),
  Link: ({ children, ...rest }: { children: React.ReactNode }) => (
    <a data-href={String(rest.to ?? "")}>{children}</a>
  ),
}));

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "2026.09" }));
vi.mock("../../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
}));

const api = vi.hoisted(() => ({
  getExpressionLibraries: vi.fn(),
  getAssemblies: vi.fn(async () => []),
}));

vi.mock("@soymutdb/api-client", () => ({
  getExpressionLibraries: api.getExpressionLibraries,
  getAssemblies: api.getAssemblies,
}));

import { Route, validateExpressionSearch } from "./index";

type RouteOptions = {
  component: React.ComponentType;
  validateSearch: (s: Record<string, unknown>) => unknown;
};
const options = (Route as unknown as { options: RouteOptions }).options;
const ExpressionLibraries = options.component;

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ExpressionLibraries />
    </QueryClientProvider>,
  );
}

function page(overrides: Partial<ExpressionLibraryPage> = {}): ExpressionLibraryPage {
  return { items: [], total: 0, page: 1, page_size: 20, ...overrides };
}

const library = {
  public_id: "SAMPLE-A",
  sample_id: "SAMPLE-A",
  library_name: "Root drought rep1",
  tissue: "root",
  treatment: "drought",
  developmental_stage: "V3",
  study_ref: "SRP000001",
  source: "NCBI SRA",
  assembly_name: "Wm82.a4.v1",
  expression_data_count: 42,
  extra_metadata: null,
};

beforeEach(() => {
  runtime.search = { page: 1, tissue: "", treatment: "", assembly: "" };
  runtime.navigate.mockReset();
  api.getExpressionLibraries.mockReset();
  api.getAssemblies.mockReset();
  api.getAssemblies.mockResolvedValue([]);
});

afterEach(() => cleanup());

describe("expression library browser", () => {
  it("narrows a raw search object into typed filter state", () => {
    expect(validateExpressionSearch({ page: "3", tissue: "root", treatment: 7 })).toEqual({
      page: 3,
      tissue: "root",
      treatment: "",
      assembly: "",
    });
    // A hostile page value cannot select a negative or NaN offset.
    expect(validateExpressionSearch({ page: "-4" }).page).toBe(1);
    expect(validateExpressionSearch({ page: "abc" }).page).toBe(1);
  });

  it("lists a library with its study reference and assembly", async () => {
    api.getExpressionLibraries.mockResolvedValue(page({ items: [library], total: 1 }));

    renderPage();

    await waitFor(() => expect(screen.getByText("SAMPLE-A")).toBeTruthy());
    expect(screen.getByText("SRP000001")).toBeTruthy();
    expect(screen.getByText("Wm82.a4.v1")).toBeTruthy();
    expect(api.getExpressionLibraries).toHaveBeenCalledWith({
      page: 1,
      page_size: 20,
    });
  });

  it("sends the URL filters to the API and keeps an unset one out of the request", async () => {
    runtime.search = { page: 2, tissue: "root", treatment: "", assembly: "4" };
    api.getExpressionLibraries.mockResolvedValue(page());

    renderPage();

    await waitFor(() =>
      expect(api.getExpressionLibraries).toHaveBeenCalledWith({
        page: 2,
        page_size: 20,
        tissue: "root",
        assembly_id: 4,
      }),
    );
  });

  it("says a library has no study reference instead of rendering a blank", async () => {
    api.getExpressionLibraries.mockResolvedValue(
      page({ items: [{ ...library, study_ref: null, assembly_name: null }], total: 1 }),
    );

    renderPage();

    await waitFor(() => expect(screen.getByText("No study reference")).toBeTruthy());
    expect(screen.getByText("Assembly not recorded")).toBeTruthy();
  });

  it("distinguishes an empty release from an empty filter result", async () => {
    api.getExpressionLibraries.mockResolvedValue(page());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("No expression libraries are available in this release")).toBeTruthy(),
    );
    cleanup();

    runtime.search = { page: 1, tissue: "leaf", treatment: "", assembly: "" };
    api.getExpressionLibraries.mockResolvedValue(page());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("No expression library matches these filters")).toBeTruthy(),
    );
  });
});
