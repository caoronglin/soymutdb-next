import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { GeneSequencePanel } from "./gene-sequence-panel";
import type { GeneSequenceAvailability } from "@soymutdb/api-client";

// The real instance lives in the app shell; these tests only need the analysed
// sentences, so return the key itself and never assert on prose.
vi.mock("react-i18next", () => {
  // Assert keys, never prose; matches the other route boundary tests.
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});

function entry(
  molecule: GeneSequenceAvailability["molecule"],
  overrides: Partial<GeneSequenceAvailability> = {},
): GeneSequenceAvailability {
  return {
    molecule,
    availability: "unavailable",
    reason: `no_sequence_store:${molecule === "cds" ? "coding_sequence" : molecule}`,
    length: null,
    checksum: null,
    sequence: null,
    ...overrides,
  };
}

describe("GeneSequencePanel", () => {
  it("states that every molecule is not imported rather than rendering an empty table", () => {
    render(
      <GeneSequencePanel
        sequences={[entry("genomic"), entry("cds"), entry("transcript"), entry("protein")]}
      />,
    );
    expect(screen.getAllByTestId("sequence-unavailable")).toHaveLength(4);
    // The reason is shown verbatim so a client can key on it.
    expect(screen.getByText("no_sequence_store:coding_sequence")).toBeTruthy();
  });

  it("never invents a residue string when the API omits the field", () => {
    const { container } = render(<GeneSequencePanel />);
    expect(screen.queryAllByTestId("sequence-unavailable")).toHaveLength(0);
    expect(container.querySelector("pre")).toBeNull();
  });

  it("renders residues, length and checksum only when the molecule is available", () => {
    render(
      <GeneSequencePanel
        sequences={[entry("protein", { availability: "available", length: 9, sequence: "MKVLAAGIV" })]}
      />,
    );
    expect(screen.getByText("MKVLAAGIV")).toBeTruthy();
    expect(screen.queryByTestId("sequence-unavailable")).toBeNull();
  });
});
