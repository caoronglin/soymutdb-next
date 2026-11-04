// @vitest-environment jsdom
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GeneFamilyList } from "@soymutdb/api-client";
import { catalogs } from "@soymutdb/i18n-core";

const runtime = vi.hoisted(() => ({
  search: { page: 1, assembly: "", level: "" } as Record<string, unknown>,
  navigate: vi.fn(),
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useSearch: () => runtime.search,
    useNavigate: () => runtime.navigate,
  }),
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "2026.09" }));
vi.mock("../../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
}));

const api = vi.hoisted(() => ({
  listFamilies: vi.fn(),
  getAssemblies: vi.fn(async () => []),
}));

vi.mock("@soymutdb/api-client", () => ({
  listFamilies: api.listFamilies,
  getAssemblies: api.getAssemblies,
}));

import { Route, validateComparativeSearch } from "./index";

type RouteOptions = { component: React.ComponentType; validateSearch: (s: Record<string, unknown>) => unknown };
const options = (Route as unknown as { options: RouteOptions }).options;
const ComparativeFamilies = options.component;

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ComparativeFamilies />
    </QueryClientProvider>,
  );
}

function page(overrides: Partial<GeneFamilyList> = {}): GeneFamilyList {
  return { items: [], total: 0, page: 1, page_size: 20, ...overrides };
}

afterEach(() => cleanup());

beforeEach(() => {
  runtime.search = { page: 1, assembly: "", level: "" };
  runtime.navigate.mockClear();
  api.listFamilies.mockReset();
});

describe("validateComparativeSearch", () => {
  it("parses the URL filters and clamps an unusable page to 1", () => {
    expect(validateComparativeSearch({ page: "3", assembly: "2", level: "gene_family" })).toEqual({
      page: 3,
      assembly: "2",
      level: "gene_family",
    });
    expect(validateComparativeSearch({ page: "-5" }).page).toBe(1);
    expect(validateComparativeSearch({ page: "abc" }).page).toBe(1);
    // An unknown level must not reach the API as a free-form string.
    expect(validateComparativeSearch({ level: "kingdom" }).level).toBe("");
  });

  it("round-trips unset filters as empty strings so a shared link stays valid", () => {
    expect(validateComparativeSearch({})).toEqual({ page: 1, assembly: "", level: "" });
  });
});

describe("comparative family list", () => {
  it("renders an empty state — not a zero count — when nothing is imported", async () => {
    api.listFamilies.mockResolvedValue(page({ items: [], total: 0 }));
    renderPage();

    await waitFor(() => expect(screen.getByTestId("comparative-empty")).toBeTruthy());
    const empty = screen.getByTestId("comparative-empty");
    const list = (catalogs.en as unknown as {
      comparative: { list: Record<string, string> };
    }).comparative.list;
    // The copy says the scope holds no import; it must not claim "0 families".
    expect(empty.textContent).toContain(list.empty);
    expect(empty.textContent).toContain(list.emptyHint);
    expect(empty.textContent).not.toContain(list.total.replace("{{total}}", "0"));
    expect(empty.textContent).not.toMatch(/\b0 families\b/);
  });

  it("passes the URL filters and page straight to the API", async () => {
    runtime.search = { page: 2, assembly: "4", level: "gene_subfamily" };
    api.listFamilies.mockResolvedValue(page({ total: 1 }));
    renderPage();

    await waitFor(() =>
      expect(api.listFamilies).toHaveBeenCalledWith({
        assembly_id: 4,
        level: "gene_subfamily",
        page: 2,
        page_size: 20,
      }),
    );
  });

  it("renders the family method and source version, not just the name", async () => {
    api.listFamilies.mockResolvedValue(
      page({
        total: 1,
        items: [
          {
            family_id: 9,
            level: "gene_family",
            external_id: "ORTHO_42",
            name: "Chalcone synthase",
            method: "orthofinder",
            method_version: "2.5.4",
            source_name: "OrthoDB",
            source_version: "v11",
            source_url: "https://example.invalid/families/ORTHO_42",
            release_id: 1,
            assembly_id: 4,
            member_count: 12,
            evidence: { kind: "predicted", source: "gene_families" },
          },
        ],
      }),
    );
    renderPage();

    await waitFor(() => expect(screen.getByText("ORTHO_42")).toBeTruthy());
    expect(screen.getByText("Chalcone synthase")).toBeTruthy();
    expect(screen.getByText(/orthofinder/)).toBeTruthy();
    expect(screen.getByText(/OrthoDB/)).toBeTruthy();
    expect(screen.queryByTestId("comparative-empty")).toBeNull();
  });
});
