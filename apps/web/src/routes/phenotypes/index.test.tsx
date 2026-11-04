// @vitest-environment jsdom
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MutantLineResponse, PhenotypeResponse } from "@soymutdb/api-client";

const runtime = vi.hoisted(() => ({
  search: { category: "", trait: "" } as Record<string, unknown>,
  navigate: vi.fn(),
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useSearch: () => runtime.search,
    useNavigate: () => runtime.navigate,
  }),
  // Forward the props the page sets on a link (data-testid / data-public-id):
  // a double that swallows them cannot tell a correct row identity from a
  // missing one.
  Link: ({
    children,
    to,
    params,
    ...rest
  }: {
    children: React.ReactNode;
    to?: string;
    params?: Record<string, string>;
  } & Record<string, unknown>) => (
    <a data-href={String(to ?? "")} data-params={JSON.stringify(params ?? {})} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "2026.09" }));
vi.mock("../../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
}));

const api = vi.hoisted(() => ({
  listMutantLines: vi.fn(),
  getMutantLinePhenotypes: vi.fn(),
}));

vi.mock("@soymutdb/api-client", () => ({
  listMutantLines: api.listMutantLines,
  getMutantLinePhenotypes: api.getMutantLinePhenotypes,
}));

import { Route, validatePhenotypesSearch } from "./index";

type RouteOptions = {
  component: React.ComponentType;
  validateSearch: (s: Record<string, unknown>) => unknown;
};
const options = (Route as unknown as { options: RouteOptions }).options;
const PhenotypesIndex = options.component;

function line(publicId: string, name = `Line ${publicId}`): MutantLineResponse {
  return { public_id: publicId, name, mutagen: null, cultivar: null, variant_count: 0 };
}

function observation(overrides: Partial<PhenotypeResponse> = {}): PhenotypeResponse {
  return {
    // The persistence key. It must never reach the DOM or a link.
    id: "991",
    mutant_line_public_id: "SMA1",
    trait_category: "morphology",
    trait_name: "Plant height",
    trait_value: "82.5",
    unit: "cm",
    description: null,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <PhenotypesIndex />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  runtime.search = { category: "", trait: "" };
  runtime.navigate.mockReset();
  api.listMutantLines.mockReset();
  api.getMutantLinePhenotypes.mockReset();
  api.listMutantLines.mockResolvedValue([line("SMA1"), line("SMB2")]);
  api.getMutantLinePhenotypes.mockImplementation(async (publicId: string) =>
    publicId === "SMA1"
      ? [observation()]
      : [
          observation({
            mutant_line_public_id: publicId,
            trait_category: "yield",
            trait_name: "Leaf width",
            trait_value: "4.2",
            unit: "cm",
          }),
        ],
  );
});

afterEach(() => cleanup());

describe("phenotype browser", () => {
  it("narrows the raw search object", () => {
    expect(validatePhenotypesSearch({ category: "yield", trait: 3 })).toEqual({
      category: "yield",
      trait: "",
    });
  });

  it("states on the page that the backend has no cross-line phenotype query", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByTestId("phenotypes-scan-boundary")).toBeTruthy());
    expect(screen.getByTestId("phenotypes-scan-boundary").textContent).toContain(
      "per mutant line",
    );
  });

  it("collects observations across lines and links each back to its line", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText("Plant height")).toBeTruthy());
    expect(screen.getByText("Leaf width")).toBeTruthy();
    const links = screen.getAllByTestId("phenotype-line-link");
    expect(links.map((link) => link.getAttribute("data-public-id"))).toEqual(["SMA1", "SMB2"]);
  });

  it("keeps the observation persistence key out of the DOM", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText("Plant height")).toBeTruthy());
    // `id: "991"` is an internal row key: it must not appear as text, as a
    // data attribute, or inside a link href.
    const html = document.body.innerHTML;
    expect(html).not.toContain("991");
    expect(html).not.toContain("data-row-key=\"991\"");
  });

  it("filters by trait category through the URL", async () => {
    runtime.search = { category: "morphology", trait: "" };
    renderPage();

    await waitFor(() => expect(screen.getByText("Plant height")).toBeTruthy());
    expect(screen.queryByText("Leaf width")).toBeNull();
  });

  it("marks an unrecorded value as not recorded rather than zero", async () => {
    // `mockImplementation` (not a one-shot resolved value): the scan issues one
    // read per line, and every read must return the same observation.
    api.getMutantLinePhenotypes.mockImplementation(async () => [
      observation({ trait_value: null, unit: null }),
    ]);

    renderPage();

    // Every scanned line returns the same observation, so the trait name shows
    // once per line; the value/unit cells are what this test is about.
    await waitFor(() => expect(screen.getAllByText("Plant height").length).toBeGreaterThan(0));
    const table = within(screen.getByRole("table"));
    expect(table.getAllByText("Not recorded").length).toBeGreaterThanOrEqual(2);
    expect(table.queryByText("0")).toBeNull();
  });

  it("reports a partial view when the public line set exceeds the scan budget", async () => {
    // One look-ahead request returns the full cap, which is what tells the page
    // it cannot claim completeness.
    api.listMutantLines.mockResolvedValue(
      Array.from({ length: 200 }, (_, index) => line(`SM${String(index).padStart(4, "0")}`)),
    );
    api.getMutantLinePhenotypes.mockResolvedValue([]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("phenotypes-scan-truncated")).toBeTruthy());
    expect(screen.getByText("Partial")).toBeTruthy();
  });

  it("says there is no public line instead of showing an empty table", async () => {
    api.listMutantLines.mockResolvedValue([]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("phenotypes-state-no-data")).toBeTruthy());
  });
});
