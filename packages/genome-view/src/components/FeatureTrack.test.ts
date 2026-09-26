import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { FeatureRecord, TrackConfig } from "@soymutdb/genome-data";
import FeatureTrack from "./FeatureTrack.vue";

const track: TrackConfig = { trackId: "genes", name: "Gene Models", type: "FeatureTrack", assemblyNames: ["v5"] };

function feature(id: string, start: number, end: number, strand: "+" | "-" = "+"): FeatureRecord {
  return { id, type: "gene", start, end, strand, assemblyKey: "v5", refName: "chr1", name: id };
}

const base = { track, assemblyKey: "v5", refName: "chr1", region: { start: 0, end: 100 }, widthPx: 100 };

describe("FeatureTrack", () => {
  it("renders one shape per visible feature with an accessible title", () => {
    const wrapper = mount(FeatureTrack, {
      props: { ...base, records: [feature("a", 0, 10), feature("b", 50, 60, "-")] },
    });
    const shapes = wrapper.findAll("rect");
    expect(shapes).toHaveLength(2);
    expect(wrapper.text()).toContain("a");
    expect(wrapper.find("svg").attributes("role")).toBe("img");
  });

  it("shows an empty state when nothing overlaps the view", () => {
    const wrapper = mount(FeatureTrack, {
      props: { ...base, records: [feature("far", 900, 1000)] },
    });
    expect(wrapper.findAll("rect")).toHaveLength(0);
    expect(wrapper.text()).toContain("No features in view");
  });

  it("shows a loading state before records arrive", () => {
    const wrapper = mount(FeatureTrack, { props: { ...base, loading: true } });
    expect(wrapper.text()).toContain("Loading features");
  });
});
