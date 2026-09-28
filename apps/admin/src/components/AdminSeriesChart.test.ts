// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import AdminSeriesChart from "./AdminSeriesChart.vue";

/**
 * The dashboard charts are hand-rolled SVG (the Vue port carries no chart
 * library). These assertions pin the two things that would silently regress:
 * a series being dropped, and the y-scale collapsing when every value is zero.
 */
const SERIES = [
  { name: "imported", color: "var(--chart-1)", values: [0, 10, 5] },
  { name: "failed", color: "var(--destructive)", values: [0, 2, 1] },
];

describe("AdminSeriesChart", () => {
  it("draws one line per series, scaled into the view box", () => {
    const wrapper = mount(AdminSeriesChart, {
      props: { title: "Imports", labels: ["a", "b", "c"], series: SERIES },
    });

    const lines = wrapper.findAll("polyline");
    expect(lines).toHaveLength(2);
    const points = (lines[0]?.attributes("points") ?? "").split(" ");
    expect(points).toHaveLength(3);
    // The peak (value 10) reaches the top edge; the origin sits on the baseline.
    expect(points[1]?.split(",")[1]).toBe("0.00");
    expect(points[0]?.split(",")[1]).toBe("100.00");
    expect(lines[1]?.attributes("stroke")).toBe("var(--destructive)");
  });

  it("draws grouped bars in the bar variant", () => {
    const wrapper = mount(AdminSeriesChart, {
      props: { title: "Imports", labels: ["a", "b", "c"], series: SERIES, variant: "bar" },
    });

    expect(wrapper.findAll("polyline")).toHaveLength(0);
    expect(wrapper.findAll("rect")).toHaveLength(6);
  });

  it("states the empty case instead of drawing an empty frame", () => {
    const wrapper = mount(AdminSeriesChart, {
      props: { title: "Imports", labels: [], series: [] },
    });

    expect(wrapper.find("svg").exists()).toBe(false);
    expect(wrapper.text()).not.toBe("");
  });

  it("does not divide by zero when every value is zero", () => {
    const wrapper = mount(AdminSeriesChart, {
      props: {
        title: "Idle",
        labels: ["a", "b"],
        series: [{ name: "idle", color: "var(--chart-1)", values: [0, 0] }],
      },
    });

    const points = wrapper.get("polyline").attributes("points") ?? "";
    expect(points).not.toContain("NaN");
    expect(points).toContain("100.00");
  });
});
