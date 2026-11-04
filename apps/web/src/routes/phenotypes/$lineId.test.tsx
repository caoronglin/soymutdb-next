// @vitest-environment jsdom
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MutantLineDetail, PhenotypeResponse } from "@soymutdb/api-client";

const runtime = vi.hoisted(() => ({ params: { lineId: "SMA1" } }));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useParams: () => runtime.params,
  }),
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "2026.09" }));
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
    getMutantLine: api.getMutantLine,
    getMutantLinePhenotypes: api.getMutantLinePhenotypes,
  };
});

import { Route } from "./$lineId";

type RouteOptions = { component: React.ComponentType };
const LineDetail = (Route as unknown as { options: RouteOptions }).options.component;

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
  id: "991",
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
      <LineDetail />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  runtime.params = { lineId: "SMA1" };
  api.getMutantLine.mockReset();
  api.getMutantLinePhenotypes.mockReset();
  api.getMutantLine.mockResolvedValue(line);
  api.getMutantLinePhenotypes.mockResolvedValue([observation]);
});

afterEach(() => cleanup());

describe("phenotype line detail", () => {
  it("shows the public id and the line's observations", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByTestId("phenotype-line-public-id")).toBeTruthy());
    expect(screen.getByTestId("phenotype-line-public-id").getAttribute("data-public-id")).toBe(
      "SMA1",
    );
    await waitFor(() => expect(screen.getByText("Plant height")).toBeTruthy());
    expect(screen.getByText("82.5")).toBeTruthy();
  });

  it("never puts the observation persistence key in the document", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText("Plant height")).toBeTruthy());
    // Ant Design renders the row key as `data-row-key`. The payload's `id` is
    // the private persistence key, so it must not survive into the DOM.
    const html = document.body.innerHTML;
    expect(html).not.toContain(observation.id);
    expect(html).not.toContain(`data-row-key="${observation.id}"`);
  });

  it("says the line has no observation instead of showing an empty table", async () => {
    api.getMutantLinePhenotypes.mockResolvedValue([]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("phenotypes-state-no-data")).toBeTruthy());
  });

  it("falls back to not-found copy for an unusable line id", async () => {
    runtime.params = { lineId: "!!!" };

    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/was not found, or it is not public/)).toBeTruthy(),
    );
    // A malformed id must not reach the API at all.
    expect(api.getMutantLine).not.toHaveBeenCalled();
  });
});
