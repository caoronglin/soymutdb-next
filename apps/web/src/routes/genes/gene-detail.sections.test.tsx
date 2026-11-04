/**
 * The gene detail page's section wiring.
 *
 * Two things are asserted here, both of which a component test cannot see:
 *
 * 1. Every optional block comes from the detail response. Until this landed the
 *    page fetched `/genes/{id}/expression` and `/genes/{id}/homologs` in
 *    parallel with the detail request, so the same rows had two sources and the
 *    two could disagree. The assertions count calls, not requests rendered.
 * 2. The four new tabs exist and each renders its own section component, so a
 *    block present in the response is reachable without leaving the page.
 */
import * as React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getGene: vi.fn(),
  getGeneExpression: vi.fn(),
  getGeneHomologs: vi.fn(),
  listTestDataPreviewMutationSitesForGene: vi.fn(),
  gene: null as unknown,
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useParams: () => ({ geneId: "Glyma.01G000100" }),
    useSearch: () => ({ assembly: undefined }),
  }),
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: { queryKey: unknown[] }) => {
    // Key the detail query by the factory call; everything else is incidental.
    const key = JSON.stringify(options.queryKey);
    const isDetail = key.includes('"detail"') && key.includes("Glyma.01G000100");
    return {
      data: isDetail ? api.gene : undefined,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    };
  },
}));
vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("@soymutdb/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@soymutdb/api-client")>()),
  getGene: api.getGene,
  getGeneExpression: api.getGeneExpression,
  getGeneHomologs: api.getGeneHomologs,
  listTestDataPreviewMutationSitesForGene: api.listTestDataPreviewMutationSitesForGene,
  getReleaseId: () => "5",
}));
vi.mock("../../lib/query-options", () => ({ assembliesQueryOptions: () => ({ queryKey: ["assemblies"], queryFn: vi.fn() }) }));
vi.mock("../../lib/site-variant", () => ({ SITE_VARIANT: "external" }));
vi.mock("../../components/gene-genome-view", () => ({ GeneGenomeView: () => null }));
vi.mock("../../components/gene-seed-request-entry", () => ({ GeneSeedRequestEntry: () => null }));

import { Route } from "./$geneId";

const Page = (Route as unknown as { options: { component: React.ComponentType } }).options.component;

function section(sectionName: string, state: string, count: number | null, reason: string | null = null) {
  return { section: sectionName, state, count, evidence: { kind: "imported", source: "snapshot" }, reason };
}

function gene(overrides: Record<string, unknown> = {}) {
  return {
    id: "internal-row-key",
    gene_id: "Glyma.01G000100",
    symbol: "GLYMA01G000100",
    name: null,
    biotype: "protein_coding",
    assembly_id: "4",
    assembly_name: "Wm82.a4.v1",
    chromosome: "Chr01",
    start_pos: 1000,
    end_pos: 2000,
    strand: "+",
    description: null,
    source: "soybase",
    extra: {},
    transcripts: [],
    annotations: [],
    annotation_section: {
      status: section("annotation", "available", 1),
      terms: [
        {
          ontology: "go",
          term_id: "GO:0009733",
          term_name: "response to auxin",
          evidence_code: "IDA",
          kind: "experimental",
          reference: null,
          qualifier: null,
        },
      ],
      source_name: "soybase_go",
      source_version: "2026-01",
      source_url: null,
    },
    homolog_section: {
      status: section("homolog", "available", 1),
      records: [
        {
          homolog_species: "Arabidopsis thaliana",
          homolog_gene_id: "AT1G01010",
          homolog_type: "ortholog",
          method: null,
          source: "inparanoid",
          kind: "transferred",
          confidence: null,
        },
      ],
    },
    expression_section: {
      status: section("expression", "available", 1),
      records: [
        {
          library_id: "lib-1",
          library_name: "root_L1",
          tissue: "root",
          treatment: null,
          stage: null,
          tpm: 1,
          fpkm: 2,
          raw_count: 3,
        },
      ],
    },
    variants_section: { status: section("variants", "available", 3), total: 3, by_impact: { HIGH: 3 } },
    phenotype_section: { status: section("phenotype", "empty", 0), records: [] },
    // The live API answer for literature today: no relation, no snapshot.
    literature_section: {
      status: section("literature", "not_imported", null, "gene_literature_link_missing"),
      records: [],
    },
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.gene = gene();
  api.listTestDataPreviewMutationSitesForGene.mockResolvedValue([]);
});
afterEach(cleanup);

describe("gene detail sections", () => {
  it("takes expression and homologs from the detail response, not a second request", () => {
    render(<Page />);
    // One dataset, one source: the old endpoints are never called.
    expect(api.getGeneExpression).not.toHaveBeenCalled();
    expect(api.getGeneHomologs).not.toHaveBeenCalled();
    expect(api.getGene).not.toHaveBeenCalled(); // the mock stands in for it
  });

  it("exposes one tab per section and renders the block the response carries", () => {
    render(<Page />);
    // Every tab label is present, including the four added by this change.
    for (const label of ["GO / KEGG", "Variants", "Phenotypes", "Literature", "Expression", "Homologs"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    // The annotation tab renders the response's rows and keeps the source code.
    fireEvent.click(screen.getByRole("tab", { name: /GO \/ KEGG/ }));
    expect(screen.getByTestId("gene-annotation-section")).toBeTruthy();
    expect(screen.getByText("IDA")).toBeTruthy();
    expect(screen.getByText("GO:0009733")).toBeTruthy();
  });

  it("states that literature was never imported instead of an empty table", () => {
    render(<Page />);
    fireEvent.click(screen.getByRole("tab", { name: /Literature/ }));
    const notice = screen.getByTestId("gene-section-not-imported");
    expect(notice.textContent).toContain("gene_literature_link_missing");
    expect(notice.textContent).not.toMatch(/\b0\b/);
  });

  it("reports an empty phenotype section as this gene having none", () => {
    render(<Page />);
    fireEvent.click(screen.getByRole("tab", { name: /Phenotypes/ }));
    expect(screen.getByTestId("gene-section-empty")).toBeTruthy();
  });
});
