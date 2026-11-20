/**
 * Homolog alignment: which accessions resolve, what is reported when they do
 * not, and the minimum for a tree.
 *
 * The point of these tests is the honest-reporting half, not the tree maths:
 * a cross-version accession this deployment does not hold must be named, not
 * silently dropped, and too few resolved sequences must say so instead of
 * producing a two-leaf "tree".
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => {
  const translation = { t: (key: string, options?: Record<string, unknown>) =>
    options && "count" in options ? `${key}:${options.count}` : key };
  return { useTranslation: () => translation };
});

const api = vi.hoisted(() => ({
  getGene: vi.fn(),
  tree: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getGene: api.getGene, sequenceApi: { ...actual.sequenceApi, tree: api.tree } };
});

import { HomologAlignment } from "./homolog-alignment";

const CDS = "ATGGCTGCTGCTTAA";

function record(accession: string) {
  return {
    homolog_gene_id: accession,
    homolog_species: "Glycine max",
    homolog_type: "ortholog",
    source: null,
  } as never;
}

function geneWithCds(sequence: string) {
  return {
    sequences: [{ molecule: "cds", availability: "available", sequence, reason: null }],
  } as never;
}

beforeEach(() => {
  api.getGene.mockReset();
  api.tree.mockReset();
});

describe("HomologAlignment", () => {
  it("runs nothing until asked", () => {
    render(<HomologAlignment records={[record("A"), record("B"), record("C")]} />);
    expect(api.getGene).not.toHaveBeenCalled();
    expect(api.tree).not.toHaveBeenCalled();
  });

  it("aligns the resolved accessions and shows the tree", async () => {
    api.getGene.mockResolvedValue(geneWithCds(CDS));
    api.tree.mockResolvedValue({
      newick: "(A:0,B:0,C:0)Inner;",
      leaf_count: 3,
      labels: ["A", "B", "C"],
      distance_model: "identity",
      method: "neighbor-joining",
      caveat: "p-distances over a progressive alignment",
    });
    render(<HomologAlignment records={[record("A"), record("B"), record("C")]} />);

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(api.tree).toHaveBeenCalledTimes(1));
    const tree = await screen.findByTestId("homolog-alignment-tree");
    expect(tree.textContent).toContain("(A:0,B:0,C:0)Inner;");
    // The API's caveat must reach the reader, not be swallowed.
    expect(tree.textContent).toContain("p-distances");
  });

  it("names an accession the database does not hold instead of dropping it", async () => {
    api.getGene
      .mockResolvedValueOnce(geneWithCds(CDS))
      .mockRejectedValueOnce(new Error("404"))
      .mockResolvedValueOnce(geneWithCds(CDS));
    api.tree.mockResolvedValue({
      newick: "(A:0,C:0);",
      leaf_count: 2,
      labels: ["A", "C"],
      distance_model: "identity",
      method: "neighbor-joining",
      caveat: "c",
    });
    render(<HomologAlignment records={[record("A"), record("MISSING"), record("C")]} />);

    fireEvent.click(screen.getByRole("button"));

    const unresolved = await screen.findByTestId("homolog-alignment-unresolved");
    expect(unresolved.textContent).toContain("MISSING");
  });

  it("refuses to build a tree from fewer than three sequences", async () => {
    api.getGene
      .mockResolvedValueOnce(geneWithCds(CDS))
      .mockRejectedValueOnce(new Error("404"));
    render(<HomologAlignment records={[record("A"), record("B")]} />);

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(screen.getByText(/tooFew/)).toBeTruthy());
    // Two sequences cannot form a tree; the compute call must not be made.
    expect(api.tree).not.toHaveBeenCalled();
  });

  it("reports an entry with no sequence for the chosen molecule", async () => {
    api.getGene.mockResolvedValue({
      sequences: [{ molecule: "cds", availability: "unavailable", sequence: null, reason: "not_imported" }],
    } as never);
    render(<HomologAlignment records={[record("A"), record("B"), record("C")]} />);

    fireEvent.click(screen.getByRole("button"));

    const unresolved = await screen.findByTestId("homolog-alignment-unresolved");
    expect(unresolved.textContent).toContain("not_imported");
    expect(api.tree).not.toHaveBeenCalled();
  });
});
