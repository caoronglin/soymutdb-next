// @vitest-environment jsdom
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GeneFamilyDetail } from "@soymutdb/api-client";
import { catalogs } from "@soymutdb/i18n-core";

const runtime = vi.hoisted(() => ({
  params: { familyId: "9" },
  search: { assembly: "" } as Record<string, unknown>,
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useParams: () => runtime.params,
    useSearch: () => runtime.search,
  }),
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "2026.09" }));
vi.mock("../../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
  ScaleIn: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("../../components/comparative/comparative-artifact-panel", () => ({
  ComparativeArtifactPanel: () => <div data-testid="artifact-panel-stub" />,
}));

const api = vi.hoisted(() => ({
  getFamily: vi.fn(),
  getAssemblies: vi.fn(async () => []),
}));

vi.mock("@soymutdb/api-client", () => ({
  getFamily: api.getFamily,
  getAssemblies: api.getAssemblies,
}));

import { Route } from "./$familyId";

const FamilyDetail = (Route as unknown as { options: { component: React.ComponentType } }).options
  .component;

function detail(overrides: Partial<GeneFamilyDetail> = {}): GeneFamilyDetail {
  return {
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
    member_count: 1,
    evidence: { kind: "predicted", source: "gene_families" },
    members: [
      {
        gene_accession: "Gm01g00010",
        species: "Glycine max",
        relationship_type: "one_to_many",
        method: "orthofinder",
        confidence: 0.9,
        evidence: null,
      },
    ],
    coverage: [
      { species: "Glycine max", state: "available", member_count: 1 },
      { species: "Glycine soja", state: "no_data", member_count: null },
    ],
    relationship_types: ["one_to_many"],
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <FamilyDetail />
    </QueryClientProvider>,
  );
}

afterEach(() => cleanup());

beforeEach(() => {
  runtime.params = { familyId: "9" };
  runtime.search = { assembly: "" };
  api.getFamily.mockReset();
});

describe("family detail provenance", () => {
  it("states method, method version, source and source version", async () => {
    api.getFamily.mockResolvedValue(detail());
    renderPage();

    await waitFor(() => expect(screen.getByTestId("family-provenance")).toBeTruthy());
    expect(screen.getByTestId("family-method").textContent).toBe("orthofinder");
    expect(screen.getByTestId("family-method-version").textContent).toBe("2.5.4");
    expect(screen.getByTestId("family-source-name").textContent).toBe("OrthoDB");
    expect(screen.getByTestId("family-source-version").textContent).toBe("v11");
  });

  it("shows a missing method as an explicit gap, never as an empty string", async () => {
    api.getFamily.mockResolvedValue(detail({ method: "" }));
    renderPage();

    await waitFor(() => expect(screen.getByTestId("family-method")).toBeTruthy());
    // An empty method is a contract violation; the page says so instead of
    // letting the cell read as a blank field.
    expect(screen.getByTestId("family-method").textContent).toBe("—");
  });
});

describe("family detail relationship types", () => {
  it("prints the three classes in the source's own vocabulary", async () => {
    api.getFamily.mockResolvedValue(
      detail({ relationship_types: ["one_to_one", "one_to_many", "many_to_many"] }),
    );
    renderPage();

    await waitFor(() => expect(screen.getByTestId("family-relationship-types")).toBeTruthy());
    for (const type of ["one_to_one", "one_to_many", "many_to_many"]) {
      const tag = document.querySelector(`[data-relationship-type="${type}"]`);
      expect(tag).toBeTruthy();
      // Untranslated: a fuzzy synonym would erase the cardinality distinction.
      expect(tag?.textContent).toBe(type);
    }
  });
});

describe("family detail coverage", () => {
  it("does not turn a species with no source record into a member count of 0", async () => {
    api.getFamily.mockResolvedValue(detail());
    renderPage();

    await waitFor(() => expect(screen.getByTestId("comparative-coverage")).toBeTruthy());
    const soja = screen.getByTestId("coverage-count-Glycine soja");
    expect(soja.textContent).toBe("—");
    expect(screen.getByTestId("coverage-count-Glycine max").textContent).toBe("1");
    // The no_data species is labelled, not silently omitted.
    expect(document.querySelector('[data-coverage-state="no_data"]')).toBeTruthy();
  });

  it("renders nothing when the family itself is absent from this release", async () => {
    api.getFamily.mockRejectedValue(new Error("Not Found"));
    renderPage();

    // The shared double resolves the catalog, so assert the copy the page
    // renders rather than the key string.
    const notFound = (catalogs.en as unknown as {
      comparative: { detail: Record<string, string> };
    }).comparative.detail.notFound;
    await waitFor(() => expect(screen.getByText(notFound)).toBeTruthy());
    expect(screen.queryByTestId("family-provenance")).toBeNull();
  });
});
