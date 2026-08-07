import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { FilterBar, type FilterItem } from "./filter-bar";

const items: FilterItem[] = [
  {
    key: "gene",
    label: "Gene",
    control: <input aria-label="Gene input" />,
    active: true,
    count: 3,
  },
  {
    key: "impact",
    label: "Impact",
    control: <select aria-label="Impact select"><option>High</option></select>,
  },
];

describe("FilterBar", () => {
  it("renders labels and controls for every item", () => {
    render(<FilterBar items={items} />);
    expect(screen.getByText("Gene")).toBeInTheDocument();
    expect(screen.getByLabelText("Gene input")).toBeInTheDocument();
    expect(screen.getByLabelText("Impact select")).toBeInTheDocument();
  });

  it("shows the active indicator and count badge", () => {
    render(<FilterBar items={items} />);
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows a clear button only when something is active and calls onClearAll", () => {
    const onClearAll = vi.fn();
    const { rerender } = render(<FilterBar items={items} onClearAll={onClearAll} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onClearAll).toHaveBeenCalledTimes(1);

    rerender(<FilterBar items={items.filter((i) => !i.active)} onClearAll={onClearAll} />);
    expect(screen.queryByRole("button", { name: "Clear all" })).not.toBeInTheDocument();
  });

  it("collapses on mobile with an accessible toggle", () => {
    render(<FilterBar items={items} defaultCollapsed />);
    const toggle = screen.getByRole("button", { name: "Filters" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});
