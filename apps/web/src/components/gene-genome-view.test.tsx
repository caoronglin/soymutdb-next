/**
 * The gene page's genome view: window, context genes and their emphasis.
 *
 * Three promises are asserted here, all of them invisible in a screenshot at
 * review time:
 *
 * 1. the window asked of the API is the gene body ±2000 bp (clamped at base 1) and
 *    the rendered window is clamped to the chromosome length the API reports;
 * 2. every gene the region query returns is drawn — the view is a locus picture,
 *    not a picture of the selected gene with decoration;
 * 3. the gene the page is about is the one drawn at full strength, while the
 *    flanking context is dimmed, and the same facts exist as text for a
 *    non-visual reader.
 */
import * as React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getRegionStructure: vi.fn(),
  region: undefined as unknown,
  failed: false,
}));

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: { queryKey: unknown[]; queryFn?: () => unknown; enabled?: boolean }) => {
    // The double stands in for the observer, so it must run the factory: the
    // assertion is which request the view would send.
    void options.queryFn?.();
    return { data: api.region, isLoading: false, isError: api.failed };
  },
}));
vi.mock("@soymutdb/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@soymutdb/api-client")>()),
  getRegionStructure: api.getRegionStructure,
}));

import { GeneGenomeView } from "./gene-genome-view";

const GENE = {
  gene_id: "Glyma.01G000100.Wm82.a6.v1",
  chromosome: "Chr01",
  start_pos: 5000,
  end_pos: 5500,
  strand: "+",
  assembly_id: "1",
  transcripts: [],
};

function regionGene(geneId: string, start: number, end: number, strand = "+") {
  return {
    gene_id: geneId,
    name: null,
    chromosome: "Chr01",
    start,
    end,
    start_pos: start,
    end_pos: end,
    strand,
    biotype: "protein_coding",
    transcripts: [],
  };
}

function structure(overrides: Record<string, unknown> = {}) {
  return {
    assembly_id: 1,
    assembly_name: "Wm82",
    assembly_version: "a6.v1",
    chromosome: "Chr01",
    chromosome_length: 250_000,
    start: 3000,
    end: 7500,
    truncated: false,
    genes: [
      // The window's own gene is returned by the region query too; it must not
      // be drawn twice.
      regionGene(GENE.gene_id, GENE.start_pos, GENE.end_pos),
      regionGene("Glyma.01G000050.Wm82.a6.v1", 3100, 4000),
      regionGene("Glyma.01G000200.Wm82.a6.v1", 6500, 7400, "-"),
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.failed = false;
  api.region = structure();
  api.getRegionStructure.mockResolvedValue(api.region);
});
afterEach(cleanup);

describe("GeneGenomeView context window", () => {
  it("asks for 2000 bp on each side of the gene, never for base 0", () => {
    render(<GeneGenomeView gene={GENE} />);
    expect(api.getRegionStructure).toHaveBeenCalledWith({
      assemblyId: "1",
      chromosome: "Chr01",
      start: 3000,
      end: 7500,
    });
  });

  it("clamps the upstream edge at base 1 for a gene near the chromosome start", () => {
    cleanup();
    render(<GeneGenomeView gene={{ ...GENE, start_pos: 500, end_pos: 900 }} />);
    expect(api.getRegionStructure).toHaveBeenCalledWith({
      assemblyId: "1",
      chromosome: "Chr01",
      start: 1,
      end: 2900,
    });
  });

  it("clamps the rendered window to the chromosome length the API reports", () => {
    api.region = structure({ chromosome_length: 6000 });
    render(<GeneGenomeView gene={GENE} />);
    // 5500 + 2000 would run past the last base of a 6000 bp chromosome.
    expect(screen.getByTestId("gene-genome-view-window").textContent).toContain(
      "Chr01:3,000–6,000",
    );
  });

  it("states the exact window and coordinates in the figure's accessible name", () => {
    render(<GeneGenomeView gene={GENE} />);
    const surface = screen.getByTestId("genome-view-surface");
    const label = surface.querySelector("svg")?.getAttribute("aria-label") ?? "";
    expect(label).toContain("Glyma.01G000100.Wm82.a6.v1");
    expect(label).toContain("Chr01:3,000");
    expect(label).toContain("7,500");
  });
});

describe("GeneGenomeView context genes", () => {
  it("draws every gene the region query returned, and the selected one only once", () => {
    render(<GeneGenomeView gene={GENE} />);
    const surface = screen.getByTestId("genome-view-surface");
    const drawn = Array.from(surface.querySelectorAll("[data-feature-id]")).map((node) =>
      node.getAttribute("data-feature-id"),
    );
    expect(new Set(drawn)).toEqual(
      new Set([
        GENE.gene_id,
        "Glyma.01G000050.Wm82.a6.v1",
        "Glyma.01G000200.Wm82.a6.v1",
      ]),
    );
    expect(drawn.filter((id) => id === GENE.gene_id)).toHaveLength(1);
  });

  it("keeps the selected gene at full strength and dims the flanking context", () => {
    render(<GeneGenomeView gene={GENE} />);
    const surface = screen.getByTestId("genome-view-surface");
    const dimmed = Array.from(surface.querySelectorAll('[data-dim="true"] [data-feature-id]')).map(
      (node) => node.getAttribute("data-feature-id"),
    );
    expect(dimmed.sort()).toEqual([
      "Glyma.01G000050.Wm82.a6.v1",
      "Glyma.01G000200.Wm82.a6.v1",
    ]);
    const selected = surface.querySelector(`[data-feature-id="${GENE.gene_id}"]`);
    expect(selected?.closest('[data-dim="true"]')).toBeNull();
  });

  it("lists every gene in the window, coordinates included, for a non-visual reader", () => {
    render(<GeneGenomeView gene={GENE} />);
    const table = screen.getByTestId("gene-context-table");
    expect(table.querySelector("caption")?.textContent).toContain("Chr01:3,000–7,500");
    for (const geneId of [GENE.gene_id, "Glyma.01G000050.Wm82.a6.v1", "Glyma.01G000200.Wm82.a6.v1"]) {
      const row = screen.getByTestId(`gene-context-row-${geneId}`);
      expect(row.textContent).toContain(geneId);
    }
    expect(screen.getByTestId(`gene-context-row-${GENE.gene_id}`).textContent).toContain(
      "Chr01:5,000–5,500",
    );
  });

  it("says so when the neighbour query failed instead of implying an empty locus", () => {
    api.failed = true;
    api.region = undefined;
    render(<GeneGenomeView gene={GENE} />);
    expect(screen.getByTestId("gene-genome-view-context-unavailable").textContent).toContain(
      "Neighbouring genes could not be loaded",
    );
    // The selected gene still draws; there is simply no context to claim.
    expect(
      screen.getByTestId("genome-view-surface").querySelector(`[data-feature-id="${GENE.gene_id}"]`),
    ).not.toBeNull();
  });
});
/**
 * The pointer readout and the gene model's exon/intron grammar.
 *
 * Both answer the same question at different levels: the picture has to say what
 * a stretch *is* (exon, intron, gene body, flank, neighbour), and the readout has
 * to agree with what is drawn under the cursor. The geometry is stubbed because
 * jsdom measures nothing; the coordinate that a stub rect produces is exactly
 * what the component would compute in a browser.
 */
const TRANSCRIPT = {
  id: "Glyma.01G000100.Wm82.a6.v1.t1",
  name: "Glyma.01G000100.1",
  start: 5000,
  end: 5500,
  is_canonical: true,
  exons: [
    { start: 5000, end: 5100 },
    { start: 5300, end: 5500 },
  ],
};

const GENE_MODEL = { ...GENE, transcripts: [TRANSCRIPT] };

// `geneContextRegion()` maps the 1-based inclusive window 3000–7500 onto the
// renderer's 0-based half-open 2999–7500.
const REGION_START = 2999;
const REGION_END = 7500;
const SURFACE_WIDTH = 1000;

function stubSurfaceRect(surface: HTMLElement): void {
  surface.getBoundingClientRect = () =>
    ({
      left: 0,
      right: SURFACE_WIDTH,
      width: SURFACE_WIDTH,
      top: 0,
      bottom: 80,
      height: 80,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect;
}

function hoverAt(surface: HTMLElement, bp: number): void {
  const fraction = (bp - REGION_START) / (REGION_END - REGION_START);
  fireEvent.pointerMove(surface, { clientX: fraction * SURFACE_WIDTH });
}

describe("GeneGenomeView pointer readout", () => {
  it("names the exon under the pointer and the intron when it moves into the gap", async () => {
    render(<GeneGenomeView gene={GENE_MODEL} />);
    const surface = screen.getByTestId("genome-view-surface");
    stubSurfaceRect(surface);

    hoverAt(surface, 5050);
    await waitFor(() =>
      expect(screen.getByTestId("genome-view-hover").textContent).toContain("Exon 1 of 2"),
    );

    hoverAt(surface, 5200);
    await waitFor(() =>
      expect(screen.getByTestId("genome-view-hover").textContent).toContain("Intron 1 of 1"),
    );
    // The coordinate survives next to the annotation, so the readout answers
    // both "where" and "what".
    expect(screen.getByTestId("genome-view-hover").textContent).toContain("5,200");
    expect(screen.getByTestId("genome-view-hover").textContent).not.toContain("Exon");
  });

  it("names a neighbour gene and a flank, not the selected gene for everything", async () => {
    render(<GeneGenomeView gene={GENE_MODEL} />);
    const surface = screen.getByTestId("genome-view-surface");
    stubSurfaceRect(surface);

    hoverAt(surface, 3500);
    await waitFor(() =>
      expect(screen.getByTestId("genome-view-hover").textContent).toContain(
        "Neighbour gene Glyma.01G000050.Wm82.a6.v1",
      ),
    );

    hoverAt(surface, 4500);
    await waitFor(() =>
      expect(screen.getByTestId("genome-view-hover").textContent).toContain(
        "Upstream flank of Glyma.01G000100.Wm82.a6.v1",
      ),
    );
  });

  it("draws exons as boxes and introns as chevrons between them", () => {
    render(<GeneGenomeView gene={GENE_MODEL} />);
    const surface = screen.getByTestId("genome-view-surface");
    const exons = Array.from(surface.querySelectorAll('[data-exon-kind="exon"]'));
    const introns = Array.from(surface.querySelectorAll('[data-intron="true"]'));
    // Two exon boxes, one intron between them: the distinction is a shape, not
    // a colour, so it survives a dimmed neighbour and a colour-vision deficiency.
    expect(exons).toHaveLength(2);
    expect(introns).toHaveLength(1);
    expect(exons.every((node) => node.tagName.toLowerCase() === "rect")).toBe(true);
    expect(introns[0].tagName.toLowerCase()).toBe("polyline");
    const [first, second] = exons.map((node) => Number(node.getAttribute("x")));
    const intronX = Number(introns[0].getAttribute("points")!.split(" ")[1].split(",")[0]);
    expect(intronX).toBeGreaterThan(first);
    expect(intronX).toBeLessThan(second);
  });
});
