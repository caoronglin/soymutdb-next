import { describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach } from "vitest";

import { catalogs } from "@soymutdb/i18n-core";
import { CoverageTable, ComparativeStateNotice, coverageCount } from "./coverage-states";
import type { SpeciesCoverage } from "@soymutdb/api-client";

// The shared double resolves the real catalog, so these assertions read the
// same copy the page renders. Comparing against the raw key would only pass
// for a double that returns keys verbatim.
vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

const EN = catalogs.en as unknown as {
  comparative: { coverage: Record<string, string> };
};
const copy = (key: string) => EN.comparative.coverage[key];

afterEach(() => cleanup());

describe("coverageCount", () => {
  it("returns null — never 0 — for a species the source has no record of", () => {
    expect(coverageCount("no_data", null)).toBeNull();
    // Even a malformed 0 must not survive next to a non-available state.
    expect(coverageCount("no_data", 0)).toBeNull();
    expect(coverageCount("not_imported", null)).toBeNull();
    expect(coverageCount("not_imported", 0)).toBeNull();
  });

  it("reports the stated count only when the species is available", () => {
    expect(coverageCount("available", 4)).toBe(4);
    expect(coverageCount("available", null)).toBeNull();
  });
});

describe("CoverageTable", () => {
  const coverage: SpeciesCoverage[] = [
    { species: "Glycine max", state: "available", member_count: 4 },
    { species: "Glycine soja", state: "no_data", member_count: null },
    { species: "Medicago truncatula", state: "not_imported", member_count: null },
  ];

  it("renders no_data as a phrase instead of a member count of zero", () => {
    render(<CoverageTable coverage={coverage} />);

    // The unavailable species must not print a numeric zero anywhere.
    const sojaCell = screen.getByTestId("coverage-count-Glycine soja");
    expect(sojaCell.textContent).toBe("—");
    expect(sojaCell.textContent).not.toContain("0");

    const medicagoCell = screen.getByTestId("coverage-count-Medicago truncatula");
    expect(medicagoCell.textContent).toBe("—");

    // The species that did contribute still shows its real count.
    expect(screen.getByTestId("coverage-count-Glycine max").textContent).toBe("4");
  });

  it("distinguishes no_data from not_imported in both copy and colour", () => {
    render(<CoverageTable coverage={coverage} />);
    const noData = document.querySelector('[data-coverage-state="no_data"]');
    const notImported = document.querySelector('[data-coverage-state="not_imported"]');

    // Two different claims cannot share one label...
    expect(noData?.textContent).toBe(copy("no_data"));
    expect(notImported?.textContent).toBe(copy("not_imported"));
    expect(copy("no_data")).not.toBe("comparative.coverage.no_data");
    expect(noData?.textContent).not.toBe(notImported?.textContent);
    // ...nor one colour.
    expect(noData?.className).not.toBe(notImported?.className);
  });
});

describe("ComparativeStateNotice", () => {
  it("renders nothing when the scope is available", () => {
    const { container } = render(<ComparativeStateNotice state="available" />);
    expect(container.innerHTML).toBe("");
  });

  it("uses a different message and tone for not_imported than for no_data", () => {
    const { container: noData } = render(<ComparativeStateNotice state="no_data" />);
    const noDataHtml = noData.innerHTML;
    cleanup();
    const { container: notImported } = render(
      <ComparativeStateNotice state="not_imported" />,
    );
    expect(notImported.innerHTML).not.toBe(noDataHtml);
    expect(notImported.textContent).toContain(copy("not_imported"));
    expect(noDataHtml).toContain(copy("no_data"));
  });
});
