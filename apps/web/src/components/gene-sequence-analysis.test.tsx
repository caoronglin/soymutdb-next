/**
 * Per-molecule analysis actions on the gene sequence panel.
 *
 * The assertions are about *which action appears for which molecule* and about
 * the request each one sends. The numbers themselves belong to Biopython, so
 * clamping them here would test the library, not this component.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => {
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});

const api = vi.hoisted(() => ({
  proteinProperties: vi.fn(),
  stats: vi.fn(),
  meltingTemp: vi.fn(),
  reverseComplement: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, sequenceApi: api };
});

import { SequenceAnalysis } from "./gene-sequence-analysis";

const PROTEIN = "MKTAYIAKQRQISFVKSHFSRQ";
const CODING = "ATGGCTGCTGCTGCTTAA";
/** Longer than a primer, so Tm must not be offered. */
const LONG_CODING = "ATG" + "GCT".repeat(100);

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

describe("SequenceAnalysis", () => {
  it("offers protein properties for a protein and nothing nucleotide-specific", () => {
    render(<SequenceAnalysis molecule="protein" sequence={PROTEIN} />);

    expect(screen.getByText("genes.sequences.analysis.proteinProperties")).toBeTruthy();
    // A nucleotide action on a protein would be rejected by the API.
    expect(screen.queryByText("genes.sequences.analysis.composition")).toBeNull();
    expect(screen.queryByText("genes.sequences.analysis.reverseComplement")).toBeNull();
  });

  it("sends the residues to the protein endpoint", async () => {
    api.proteinProperties.mockResolvedValue({
      length: 22,
      molecular_weight: 2655.09,
      isoelectric_point: 11.17,
      aromaticity: 0.09,
      instability_index: 12.3,
      gravy: -0.6591,
      extinction_coefficient: [1000, 2000],
      amino_acid_composition: {},
    });
    render(<SequenceAnalysis molecule="protein" sequence={PROTEIN} />);

    fireEvent.click(screen.getByText("genes.sequences.analysis.proteinProperties"));

    await waitFor(() => expect(api.proteinProperties).toHaveBeenCalledWith({ protein: PROTEIN }));
    expect(await screen.findByTestId("sequence-protein-properties")).toBeTruthy();
  });

  it("offers Tm for a primer-length nucleotide sequence", () => {
    render(<SequenceAnalysis molecule="cds" sequence={CODING} />);

    expect(screen.getByText("genes.sequences.analysis.composition")).toBeTruthy();
    expect(screen.getByText("genes.sequences.analysis.meltingTemp")).toBeTruthy();
    expect(screen.getByText("genes.sequences.analysis.reverseComplement")).toBeTruthy();
  });

  it("withholds Tm for a sequence too long to be a primer", () => {
    render(<SequenceAnalysis molecule="cds" sequence={LONG_CODING} />);

    expect(screen.getByText("genes.sequences.analysis.composition")).toBeTruthy();
    // A 300 bp stretch is not an oligo; a Tm would be a misleading number.
    expect(screen.queryByText("genes.sequences.analysis.meltingTemp")).toBeNull();
  });

  it("shows the reverse complement in place", async () => {
    api.reverseComplement.mockResolvedValue({
      sequence: "TTAAGCAGCAGCCAT",
      length: 16,
      alphabet: "dna",
      engine: { engine: "biopython", engine_version: "1.88", request_id: null },
    });
    render(<SequenceAnalysis molecule="cds" sequence={CODING} />);

    fireEvent.click(screen.getByText("genes.sequences.analysis.reverseComplement"));

    await waitFor(() => expect(api.reverseComplement).toHaveBeenCalledWith({ sequence: CODING }));
    const output = await screen.findByTestId("sequence-reverse-complement");
    expect(output.textContent).toBe("TTAAGCAGCAGCCAT");
  });

  it("surfaces a failure instead of leaving the button spinning", async () => {
    api.stats.mockRejectedValue(new Error("engine unavailable"));
    render(<SequenceAnalysis molecule="cds" sequence={CODING} />);

    fireEvent.click(screen.getByText("genes.sequences.analysis.composition"));

    expect(await screen.findByText("engine unavailable")).toBeTruthy();
    // The action must be clickable again, not stuck loading.
    const button = screen.getByText("genes.sequences.analysis.composition").closest("button");
    expect(button?.hasAttribute("disabled")).toBeFalsy();
  });

  it("runs nothing until a reader asks", () => {
    render(<SequenceAnalysis molecule="protein" sequence={PROTEIN} />);

    // Mounting a gene page must not fire compute requests.
    expect(api.proteinProperties).not.toHaveBeenCalled();
    expect(api.stats).not.toHaveBeenCalled();
    expect(api.meltingTemp).not.toHaveBeenCalled();
    expect(api.reverseComplement).not.toHaveBeenCalled();
  });
});
