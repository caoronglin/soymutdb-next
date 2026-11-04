// @vitest-environment jsdom
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DiversityResponse, LdResponse } from "@soymutdb/api-client";

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({ ...options, options }),
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "2026.09" }));

const api = vi.hoisted(() => ({
  computeLd: vi.fn(),
  computeDiversity: vi.fn(),
  computeAlleleFreq: vi.fn(),
  getAssemblies: vi.fn(async () => []),
}));

vi.mock("@soymutdb/api-client", () => ({
  computeLd: api.computeLd,
  computeDiversity: api.computeDiversity,
  computeAlleleFreq: api.computeAlleleFreq,
  getAssemblies: api.getAssemblies,
}));

import { Route as LdRoute, parseGenotypes } from "./ld";
import { Route as DiversityRoute, formatPi } from "./diversity";
import { Route as AlleleFreqRoute, formatFrequency } from "./allelefreq";
import { ldChartState, toLdCells } from "./-popgen-charts";

type RouteOptions = { component: React.ComponentType };
function componentOf(route: unknown): React.ComponentType {
  return (route as { options: RouteOptions }).options.component;
}
const Ld = componentOf(LdRoute);
const Diversity = componentOf(DiversityRoute);
const AlleleFreq = componentOf(AlleleFreqRoute);

function renderWith(node: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>);
}

/**
 * Fill the gene accession (the form starts in gene mode with an empty field, so
 * submitting straight away is a validation error, not a request) and submit.
 */
function submitGeneQuery(prefix: string) {
  const geneInput = document.getElementById(`${prefix}-gene`);
  if (!geneInput) throw new Error(`gene input ${prefix}-gene not found`);
  fireEvent.change(geneInput, { target: { value: "Glyma.01G000100" } });
  fireEvent.click(screen.getByRole("button", { name: /Run analysis/i }));
}

const ldResponse = (overrides: Partial<LdResponse> = {}): LdResponse => ({
  source: "gene",
  gene_id: "Glyma.01G000100",
  assembly: "Wm82.a4.v1",
  chromosome: "chr01",
  start: 1000,
  end: 2000,
  n_variants: 2,
  variants: [
    { variant_id: "v1", chromosome: "chr01", position: 1000, ref_allele: "A", alt_allele: "G" },
    { variant_id: "v2", chromosome: "chr01", position: 1200, ref_allele: "C", alt_allele: "T" },
  ],
  r_squared: null,
  note: "per-sample genotypes are required to compute LD",
  details: null,
  ...overrides,
});

beforeEach(() => {
  api.computeLd.mockReset();
  api.computeDiversity.mockReset();
  api.computeAlleleFreq.mockReset();
});

afterEach(() => cleanup());

describe("ldChartState", () => {
  it("treats a null r_squared as not computable, not as zero LD", () => {
    expect(ldChartState({ r_squared: null, n_variants: 5 })).toBe("no-genotypes");
  });

  it("reports an empty region separately from missing genotypes", () => {
    expect(ldChartState({ r_squared: null, n_variants: 0 })).toBe("no-variants");
  });

  it("draws a real matrix when genotype data was supplied", () => {
    expect(
      ldChartState({
        r_squared: [
          [1, 0.4],
          [0.4, 1],
        ],
        n_variants: 2,
      }),
    ).toBe("matrix");
  });
});

describe("toLdCells", () => {
  it("flattens the mirrored matrix once per pair, keeping the diagonal", () => {
    const cells = toLdCells(
      ldResponse({
        r_squared: [
          [1, 0.4],
          [0.4, 1],
        ],
      }),
    );
    expect(cells.map((cell) => `${cell.x}/${cell.y}`)).toEqual(["v1/v1", "v1/v2", "v2/v2"]);
    expect(cells.map((cell) => cell.value)).toEqual([1, 0.4, 1]);
  });

  it("returns no cells at all for a null matrix", () => {
    expect(toLdCells(ldResponse())).toEqual([]);
  });
});

describe("parseGenotypes", () => {
  it("parses a header plus dosage rows", () => {
    const parsed = parseGenotypes("sample\tv1\tv2\ns1\t0\t2\ns2\t1\t1");
    expect(parsed.error).toBeNull();
    expect(parsed.matrix).toEqual({
      sample_ids: ["s1", "s2"],
      variant_ids: ["v1", "v2"],
      values: [
        [0, 2],
        [1, 1],
      ],
    });
  });

  it("rejects a ragged row rather than inventing a missing call", () => {
    expect(parseGenotypes("sample\tv1\tv2\ns1\t0").error).toBe("shape");
  });

  it("rejects a dosage that is not 0/1/2", () => {
    expect(parseGenotypes("sample\tv1\tv2\ns1\t0\t3\ns2\t1\t1").error).toBe("value");
  });

  it("rejects fewer than two samples", () => {
    expect(parseGenotypes("sample\tv1\tv2\ns1\t0\t2").error).toBe("labels");
  });

  it("returns nothing for an empty box", () => {
    expect(parseGenotypes("   \n ")).toEqual({ matrix: null, error: null });
  });
});

describe("number formatting never turns unknown into zero", () => {
  it("formats an absent frequency as the caller's label", () => {
    expect(formatFrequency(null, "Not recorded")).toBe("Not recorded");
    expect(formatFrequency(0, "Not recorded")).toBe("0.000");
  });

  it("formats an absent π as null so the caller can explain it", () => {
    expect(formatPi(null)).toBeNull();
    expect(formatPi(0)).toBe("0.000");
  });
});

describe("LD page", () => {
  it("explains that r² is not computable instead of drawing an empty matrix", async () => {
    api.computeLd.mockResolvedValue(ldResponse());

    renderWith(<Ld />);
    // The store's limitation is stated before any query is run.
    expect(screen.getByTestId("ld-genotype-notice")).toBeTruthy();

    submitGeneQuery("ld");

    await waitFor(() => expect(screen.getByTestId("ld-no-genotypes-panel")).toBeTruthy());
    expect(screen.getByTestId("ld-r2-state").textContent).toBe("r² not computable");
    expect(screen.getByTestId("ld-r2-null-explanation").textContent).toContain(
      "allele frequencies only",
    );
    // The server's own note is surfaced verbatim, not paraphrased away.
    expect(screen.getByTestId("ld-r2-null-explanation").textContent).toContain(
      "per-sample genotypes are required",
    );
  });

  it("draws the matrix when genotype data is supplied", async () => {
    api.computeLd.mockResolvedValue(
      ldResponse({
        r_squared: [
          [1, 0.25],
          [0.25, 1],
        ],
      }),
    );

    renderWith(<Ld />);
    submitGeneQuery("ld");

    await waitFor(() => expect(screen.getByTestId("ld-r2-state").textContent).toBe("r² computed"));
    expect(screen.queryByTestId("ld-no-genotypes-panel")).toBeNull();
  });
});

describe("diversity page", () => {
  const response = (overrides: Partial<DiversityResponse> = {}): DiversityResponse => ({
    source: "gene",
    gene_id: "Glyma.01G000100",
    assembly: "Wm82.a4.v1",
    chromosome: "chr01",
    start: 1,
    end: 1000,
    n_bp: 1000,
    n_variants: 3,
    segregating_sites: 2,
    pi: 0.0004,
    pi_per_site: 0.2,
    theta: null,
    windows: null,
    ...overrides,
  });

  it("distinguishes 'no sample size' from 'no segregating site'", async () => {
    api.computeDiversity.mockResolvedValue(response());

    renderWith(<Diversity />);
    submitGeneQuery("dv");

    await waitFor(() =>
      expect(screen.getByTestId("theta-explanation").textContent).toContain(
        "no sample size was supplied",
      ),
    );
  });

  it("says the region has no variant instead of showing empty statistics", async () => {
    api.computeDiversity.mockResolvedValue(
      response({ n_variants: 0, segregating_sites: 0, pi: null, pi_per_site: null }),
    );

    renderWith(<Diversity />);
    submitGeneQuery("dv");

    await waitFor(() => expect(screen.getByText("No variant in this region")).toBeTruthy());
  });
});

describe("allele-frequency page", () => {
  it("marks an unrecorded frequency instead of printing zero", async () => {
    api.computeAlleleFreq.mockResolvedValue({
      source: "gene",
      gene_id: "Glyma.01G000100",
      assembly: "Wm82.a4.v1",
      chromosome: "chr01",
      start: 1,
      end: 1000,
      n_variants: 1,
      variants: [
        {
          variant_id: "v1",
          chromosome: "chr01",
          position: 100,
          ref_allele: "A",
          alt_allele: "G",
          allele_frequency: null,
          variant_type: "SNP",
          gene_id: "Glyma.01G000100",
        },
      ],
    });

    renderWith(<AlleleFreq />);
    submitGeneQuery("af");

    await waitFor(() => expect(screen.getByText("v1")).toBeTruthy());
    expect(screen.getByText("Not recorded")).toBeTruthy();
    expect(screen.queryByText("0.000")).toBeNull();
  });
});
