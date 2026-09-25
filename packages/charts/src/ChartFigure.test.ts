// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import { ChartFigure, categoryBarChart } from "./index";

// The chart runtime needs a measured viewport, which jsdom does not provide; the
// graphic's own rendering is the runtime's contract, not this package's. What
// this suite must prove is the accessible wrapper: name, description, the exact
// value table, and the empty state.
vi.mock("@tanstack/vue-charts", () => ({
  Chart: {
    props: ["definition", "data", "height"],
    template: '<svg :data-height="height" :data-points="data.length" />',
  },
}));

interface Row {
  category: string;
  value: number;
}

const DATA: readonly Row[] = [
  { category: "chr01", value: 12 },
  { category: "chr02", value: 0 },
];

function mountFigure(data: readonly Row[] = DATA) {
  return mount(ChartFigure, {
    props: {
      definition: categoryBarChart(data),
      data,
      label: "Variants per chromosome",
      description: "Number of variants observed on each chromosome.",
      tableColumns: ["Chromosome", "Variants"],
      tableRow: (datum: Row) => [datum.category, String(datum.value)],
    },
  });
}

describe("ChartFigure", () => {
  it("renders the exact values in a table, not only in the graphic", () => {
    const wrapper = mountFigure();

    // The graphic carries an accessible name and description.
    expect(wrapper.get('[role="img"]').attributes("aria-label")).toBe("Variants per chromosome");
    expect(wrapper.get('[role="img"]').attributes("aria-describedby")).toBe("chart-description");
    expect(wrapper.get("#chart-description").text()).toContain("Number of variants");

    // ...and the same numbers are readable without seeing the SVG.
    const values = wrapper.get('[data-testid="chart-values"]');
    expect(values.findAll("tbody tr")).toHaveLength(2);
    expect(values.text()).toContain("chr01");
    expect(values.text()).toContain("12");
    // A zero is a zero, not a blank: an absent value and a measured zero must
    // never look the same.
    expect(values.text()).toContain("0");
    wrapper.unmount();
  });

  it("renders an empty state instead of a placeholder series", () => {
    const wrapper = mountFigure([]);

    expect(wrapper.get('[data-testid="chart-empty"]').text()).toContain("No data");
    expect(wrapper.find('[role="img"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
