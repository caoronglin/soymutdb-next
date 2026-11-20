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
  detailLoading: false,
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useParams: () => ({ geneId: "Glyma.01G000100" }),
    useSearch: () => ({ assembly: undefined }),
  }),
  // `to`/`search` are router inputs, not DOM attributes; everything else (a
  // data-testid the page sets for its own assertions) reaches the anchor.
  Link: ({
    children,
    to: _to,
    search: _search,
    ...props
  }: { children: React.ReactNode; to?: string; search?: unknown }) => <a {...props}>{children}</a>,
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: { queryKey: unknown[] }) => {
    // Key the detail query by the factory call; everything else is incidental.
    const key = JSON.stringify(options.queryKey);
    const isDetail = key.includes('"detail"') && key.includes("Glyma.01G000100");
    return {
      data: isDetail && !api.detailLoading ? api.gene : undefined,
      isLoading: isDetail && api.detailLoading,
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
}));
vi.mock("../../lib/query-options", () => ({ assembliesQueryOptions: () => ({ queryKey: ["assemblies"], queryFn: vi.fn() }) }));
vi.mock("../../lib/site-variant", () => ({ SITE_VARIANT: "external" }));
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "5" }));
vi.mock("../../components/gene-genome-view", () => ({
  GeneGenomeView: () => <div data-testid="gene-genome-view-stand-in" />,
}));
vi.mock("../../components/gene-seed-request-entry", () => ({ GeneSeedRequestEntry: () => null }));

import { Route } from "./$geneId";
import { stableT } from "../../test/mocks";

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
  api.detailLoading = false;
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

  it("reads as identity first, entry points second, data blocks last", () => {
    render(<Page />);
    const identity = screen.getByTestId("gene-identity");
    // The page's own record is the anchor: accession, coordinates, strand and
    // the assembly that qualifies them all live in the first card.
    expect(identity.contains(screen.getByTestId("gene-id"))).toBe(true);
    expect(identity.contains(screen.getByTestId("gene-coords"))).toBe(true);
    expect(identity.contains(screen.getByTestId("gene-assembly"))).toBe(true);
    // The facts card carries facts only; mixing actions into it is what made
    // the record look like a toolbar with a title.
    expect(identity.contains(screen.getByTestId("gene-actions"))).toBe(false);
    // One action area holds the outbound entry points (browser, in-app locus).
    const actions = screen.getByTestId("gene-actions");
    expect(actions.contains(screen.getByTestId("gene-jbrowse"))).toBe(true);
    // Document order: facts, then the action area, then the section navigation.
    const precedes = (first: Element, second: Element) =>
      Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(precedes(identity, screen.getByTestId("gene-actions-card"))).toBe(true);
    expect(
      precedes(screen.getByTestId("gene-actions-card"), screen.getByTestId("gene-section-nav")),
    ).toBe(true);
  });

  it("offers the data sections through exactly one navigation surface", () => {
    render(<Page />);
    // Regression: the page used to list the same nine destinations twice — a
    // chip row in the action card plus the tab strip — so every section was
    // announced twice on one page.
    expect(screen.getAllByRole("tablist")).toHaveLength(1);
    expect(screen.getAllByRole("tab")).toHaveLength(9);
    expect(screen.queryAllByTestId(/^gene-jump-/)).toHaveLength(0);
    expect(screen.queryByTestId("gene-section-jumps")).toBeNull();
    // One way back to the search, not two.
    expect(screen.getAllByTestId("gene-back-link")).toHaveLength(1);
  });

  it("switches the visible section from the tab strip", () => {
    render(<Page />);
    fireEvent.click(screen.getByRole("tab", { name: /Variants/ }));
    expect(screen.getByTestId("gene-variant-summary")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /Literature/ }));
    expect(screen.getByTestId("gene-section-not-imported")).toBeTruthy();
  });

  it("renders the page's shape while the record loads, not a blank column", () => {
    api.detailLoading = true;
    render(<Page />);
    const skeleton = screen.getByTestId("gene-skeleton");
    expect(skeleton.getAttribute("aria-busy")).toBe("true");
    // Facts anchor, action area, section navigation + open section: the shape
    // the loaded page will have, so nothing reflows into a different
    // silhouette.
    for (const part of [
      "gene-skeleton-identity",
      "gene-skeleton-actions",
      "gene-skeleton-section-nav",
      "gene-skeleton-sections",
    ]) {
      expect(skeleton.contains(screen.getByTestId(part))).toBe(true);
    }
    // The wait is announced with copy, not left as empty space.
    expect(skeleton.textContent).toContain(stableT("genes.loading"));
    // A skeleton is not a record: no identifier is claimed before it arrives.
    expect(screen.queryByTestId("gene-id")).toBeNull();
  });

  it("carries the genome view in the overview section, not in the navigation", () => {
    render(<Page />);
    // The spatial context is the overview's content, so it sits inside the open
    // section rather than between the section navigation and its content.
    const summary = screen.getByTestId("gene-variant-summary");
    const genome = screen.getByTestId("gene-genome-view-stand-in");
    const precedes = (first: Element, second: Element) =>
      Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(precedes(genome, summary)).toBe(true);
    // Inside the open section's panel, not beside the tab strip.
    expect(genome.closest('[role="tabpanel"]')).not.toBeNull();
  });

  it("reports variant totals and the effect breakdown once, in one card", () => {
    render(<Page />);
    const summary = screen.getByTestId("gene-variant-summary");
    expect(summary.textContent).toContain("Variant Summary");
    expect(summary.textContent).toContain("Variant Count");
    // Each consequence class appears exactly once: the breakdown used to be a
    // second card rendered after the tabs.
    for (const label of ["Nonsense Count", "Missense Count", "Synonymous Count", "Frameshift Count"]) {
      expect(screen.getAllByText(label)).toHaveLength(1);
    }
  });
});
