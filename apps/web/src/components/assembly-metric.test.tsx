import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { AssemblyMetricText, hasCount, metricReasonKey } from "./assembly-metric";

// Assert keys, never prose; matches the other route boundary tests.
vi.mock("react-i18next", () => {
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});

function metric(value: number | null, reason: string | null = null) {
  return { value, reason };
}

describe("AssemblyMetricText", () => {
  it("prints a genuine zero as a number, not as 'not counted'", () => {
    render(<AssemblyMetricText metric={metric(0)} testId="m" />);
    const node = screen.getByTestId("m");
    expect(node.dataset.metricState).toBe("known");
    expect(node.textContent).toBe("0");
  });

  it("says a count could not be derived instead of printing zero", () => {
    render(<AssemblyMetricText metric={metric(null, "no_genes")} testId="m" />);
    const node = screen.getByTestId("m");
    expect(node.dataset.metricState).toBe("unknown");
    expect(node.dataset.metricReason).toBe("no_genes");
    expect(node.textContent).toBe("assemblies.metric.unknown");
    expect(node.textContent).not.toContain("0");
  });

  it("keeps an unrecognised reason visible rather than dropping it", () => {
    render(<AssemblyMetricText metric={metric(null, "brand_new_reason")} testId="m" />);
    expect(screen.getByTestId("m").dataset.metricReason).toBe("brand_new_reason");
  });

  it("renders an absent metric as not counted, never as a number", () => {
    render(<AssemblyMetricText metric={undefined} testId="m" />);
    expect(screen.getByTestId("m").dataset.metricState).toBe("unknown");
  });

  it("scales genome sizes but keeps the exact value in the title", () => {
    render(<AssemblyMetricText metric={metric(1_000_000)} basePairs testId="m" />);
    const node = screen.getByTestId("m");
    expect(node.textContent).toBe("1.0 Mb");
    expect(node.getAttribute("title")).toBe("1,000,000 bp");
  });
});

describe("metric helpers", () => {
  it("hasCount is false only for an absent value", () => {
    expect(hasCount(metric(0))).toBe(true);
    expect(hasCount(metric(null, "no_genes"))).toBe(false);
    expect(hasCount(undefined)).toBe(false);
  });

  it("maps a known reason to a translation key and rejects an unknown one", () => {
    expect(metricReasonKey("no_chromosomes")).toBe("assemblies.metric.reason.no_chromosomes");
    expect(metricReasonKey("mystery")).toBeNull();
    expect(metricReasonKey(null)).toBeNull();
  });
});
