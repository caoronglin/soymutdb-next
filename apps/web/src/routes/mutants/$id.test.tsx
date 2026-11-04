// @vitest-environment jsdom
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MutantLineDetail, PhenotypeResponse } from "@soymutdb/api-client";

const runtime = vi.hoisted(() => ({ params: { id: "SMA1" } }));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useParams: () => runtime.params,
  }),
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("../../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
}));

const api = vi.hoisted(() => ({
  getMutantLine: vi.fn(),
  getMutantLinePhenotypes: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async () => {
  const actual = await vi.importActual<typeof import("@soymutdb/api-client")>(
    "@soymutdb/api-client",
  );
  return {
    isMutantLineId: actual.isMutantLineId,
    getReleaseId: () => "2026.09",
    getMutantLine: api.getMutantLine,
    getMutantLinePhenotypes: api.getMutantLinePhenotypes,
  };
});

import { Route } from "./$id";

type RouteOptions = { component: React.ComponentType };
const MutantDetail = (Route as unknown as { options: RouteOptions }).options.component;

const line: MutantLineDetail = {
  public_id: "SMA1",
  name: "SMA1",
  mutagen: "EMS",
  cultivar: "Williams 82",
  variant_count: 3,
  species: "Glycine max",
  description: null,
  generation: "M3",
  phenotype_summary: null,
  is_public: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const observation: PhenotypeResponse = {
  id: "911911",
  mutant_line_public_id: "SMA1",
  trait_category: "morphology",
  trait_name: "Plant height",
  trait_value: "82.5",
  unit: "cm",
  description: null,
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MutantDetail />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  runtime.params = { id: "SMA1" };
  api.getMutantLine.mockReset();
  api.getMutantLinePhenotypes.mockReset();
  api.getMutantLine.mockResolvedValue(line);
  api.getMutantLinePhenotypes.mockResolvedValue([observation]);
});

afterEach(() => cleanup());

describe("mutant line detail", () => {
  it("renders the line's observations", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText("Plant height")).toBeTruthy());
    expect(screen.getByText("82.5")).toBeTruthy();
  });

  it("never puts the observation persistence key in the document", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText("Plant height")).toBeTruthy());
    // Ant Design renders the row key as `data-row-key`. The payload's `id` is
    // the private persistence key, so it must not survive into the DOM here
    // either — this page renders the same `PhenotypeResponse` table as
    // `/phenotypes/$lineId`, and regression-tested `rowKey="id"` once leaked it.
    const html = document.body.innerHTML;
    expect(html).not.toContain(observation.id);
    expect(html).not.toContain(`data-row-key="${observation.id}"`);
  });
});

describe("mutant line detail — row identity", () => {
  // A table with ONE row has exactly one distinct key, so *any* row-key
  // strategy produces unique keys and passes. That is why `rowKey="id"` (the
  // persistence key) survived here: the leak path and the correctness path both
  // rendered the same DOM. Two observations make uniqueness a real assertion.
  const second: PhenotypeResponse = {
    id: "911912",
    mutant_line_public_id: "SMA1",
    trait_category: "morphology",
    trait_name: "Pod number",
    trait_value: "41",
    unit: "count",
    description: null,
  };

  beforeEach(() => {
    api.getMutantLinePhenotypes.mockResolvedValue([observation, second]);
  });

  it("keeps two observations with distinct row keys and hides their internal ids", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText("Plant height")).toBeTruthy());
    await waitFor(() => expect(screen.getByText("Pod number")).toBeTruthy());

    const keys = [...document.body.querySelectorAll("[data-row-key]")].map(
      (node) => node.getAttribute("data-row-key") ?? "",
    );
    expect(keys.length).toBeGreaterThanOrEqual(2);
    expect(new Set(keys).size).toBe(keys.length);

    const html = document.body.innerHTML;
    for (const internal of [observation.id, second.id]) {
      expect(html).not.toContain(internal);
    }
  });

  // The render tuple is keyed on the observation's *content*, so a second page
  // of observations reuses the row. Pinning the shape keeps the tuple from
  // silently growing a field that is stable across rows (the internal id) or
  // dropping one that separates them.
  it("derives the row key from the public tuple, not from the payload id", async () => {
    const { phenotypeRowKey } = await import("../phenotypes/$lineId");
    const a = phenotypeRowKey(observation, "SMA1");
    const b = phenotypeRowKey(second, "SMA1");
    expect(a).not.toBe(b);
    expect(a).not.toContain(observation.id);
    expect(b).not.toContain(second.id);
    expect(a).toBe(phenotypeRowKey({ ...observation, id: "999999" }, "SMA1"));
  });
});
