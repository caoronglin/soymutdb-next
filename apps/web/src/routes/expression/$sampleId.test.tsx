// @vitest-environment jsdom
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExpressionLibrary, ExpressionSearchPage } from "@soymutdb/api-client";

const runtime = vi.hoisted(() => ({ params: { sampleId: "SAMPLE-A" } }));

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
  getExpressionLibrary: vi.fn(),
  searchExpression: vi.fn(),
}));

vi.mock("@soymutdb/api-client", () => ({
  getExpressionLibrary: api.getExpressionLibrary,
  searchExpression: api.searchExpression,
}));

import { Route, isExpressionSampleId } from "./$sampleId";

type RouteOptions = { component: React.ComponentType };
const options = (Route as unknown as { options: RouteOptions }).options;
const ExpressionLibraryDetail = options.component;

const library: ExpressionLibrary = {
  public_id: "SAMPLE-A",
  sample_id: "SAMPLE-A",
  library_name: "Root drought rep1",
  tissue: "root",
  treatment: "drought",
  developmental_stage: "V3",
  study_ref: "SRP000001",
  source: "NCBI SRA",
  assembly_name: "Wm82.a4.v1",
  expression_data_count: 2,
  extra_metadata: { platform: "Illumina", layout: "PE" },
};

function row(gene: string, fpkm: number | null, tpm: number | null) {
  return {
    gene_id: gene,
    library_public_id: "SAMPLE-A",
    library_name: "Root drought rep1",
    tissue: "root",
    treatment: "drought",
    fpkm,
    tpm,
    raw_count: fpkm === null ? null : Math.round(fpkm * 10),
  };
}

function page(overrides: Partial<ExpressionSearchPage> = {}): ExpressionSearchPage {
  return { items: [], total: 0, page: 1, page_size: 100, ...overrides };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ExpressionLibraryDetail />
    </QueryClientProvider>,
  );
}

/** The measurement table: the one carrying the FPKM header. */
async function findMeasureTable(): Promise<HTMLElement> {
  let found: HTMLElement | undefined;
  await waitFor(() => {
    found = screen
      .getAllByRole("table")
      .find((table) => (table.textContent ?? "").includes("FPKM (fragments per kb per million)"));
    expect(found).toBeTruthy();
  });
  return found as HTMLElement;
}

beforeEach(() => {
  runtime.params = { sampleId: "SAMPLE-A" };
  api.getExpressionLibrary.mockReset();
  api.searchExpression.mockReset();
  api.getExpressionLibrary.mockResolvedValue(library);
  api.searchExpression.mockResolvedValue(page());
});

afterEach(() => cleanup());

describe("expression library detail", () => {
  it("rejects a path value that is not a public sample id", () => {
    expect(isExpressionSampleId("SAMPLE-A")).toBe(true);
    expect(isExpressionSampleId("")).toBe(false);
    expect(isExpressionSampleId("../etc/passwd")).toBe(false);
    expect(isExpressionSampleId("a".repeat(65))).toBe(false);
  });

  it("renders study, source, assembly and developmental stage as provenance", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByTestId("expression-study-ref")).toBeTruthy());
    expect(screen.getByTestId("expression-study-ref").textContent).toBe("SRP000001");
    expect(screen.getByTestId("expression-source").textContent).toBe("NCBI SRA");
    expect(screen.getByTestId("expression-assembly").textContent).toBe("Wm82.a4.v1");
    expect(screen.getByTestId("expression-stage").textContent).toBe("V3");
  });

  it("renders extra metadata, and says so when there is none", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("expression-extra-metadata")).toBeTruthy());
    expect(screen.getByTestId("expression-extra-metadata").textContent).toContain("platform");
    cleanup();

    api.getExpressionLibrary.mockResolvedValue({ ...library, extra_metadata: null });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("This library carries no additional metadata.")).toBeTruthy(),
    );
  });

  it("states the measurement unit in the column headers", async () => {
    api.searchExpression.mockResolvedValue(
      page({ items: [row("Glyma.01G000100", 12.5, 8.25)], total: 1 }),
    );

    renderPage();

    // The chart's exact-value table is also a <table>; the measurement table is
    // the one whose header names the normalisation.
    const table = within(await findMeasureTable());
    // A header that just says "Value" hides which normalisation was measured.
    // Match the column header cell, not antd's hidden width-measurement copy.
    const headers = table.getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(headers).toContain("FPKM (fragments per kb per million)");
    expect(headers).toContain("TPM (transcripts per million)");
    expect(headers).toContain("Raw read count");
    expect(table.getByText("12.5")).toBeTruthy();
    expect(table.getByText("8.25")).toBeTruthy();
  });

  it("shows a missing measurement as a dash, never as zero", async () => {
    api.searchExpression.mockResolvedValue(
      page({ items: [row("Glyma.02G000200", null, null)], total: 1 }),
    );

    renderPage();

    const table = within(await findMeasureTable());
    expect(table.getByText("Glyma.02G000200")).toBeTruthy();
    // Three dashes: FPKM, TPM and raw count. A 0 would claim the gene was silent.
    expect(table.getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(table.queryByText("0")).toBeNull();
  });

  it("says the library has no expression rows instead of drawing an empty chart", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByTestId("expression-rows-no-data")).toBeTruthy());
    expect(api.searchExpression).toHaveBeenCalledWith({
      library: "SAMPLE-A",
      page: 1,
      page_size: 100,
    });
  });

  it("never asks the API for an internal identifier", async () => {
    renderPage();
    await waitFor(() => expect(api.getExpressionLibrary).toHaveBeenCalledWith("SAMPLE-A"));
    await waitFor(() => expect(api.searchExpression).toHaveBeenCalled());
    expect(api.searchExpression).toHaveBeenCalledWith(
      expect.objectContaining({ library: "SAMPLE-A" }),
    );
  });
});
