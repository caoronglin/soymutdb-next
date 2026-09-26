import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { TrackConfig, VariantRecord } from "@soymutdb/genome-data";
import VariantTrack from "./VariantTrack.vue";

const track: TrackConfig = { trackId: "variants", name: "SNPs & Indels", type: "VariantTrack", assemblyNames: ["v5"] };
const base = { track, assemblyKey: "v5", refName: "chr1", region: { start: 0, end: 100 }, widthPx: 100 };

function variant(id: string, start: number, end: number, kind: VariantRecord["kind"]): VariantRecord {
  return { id, assemblyKey: "v5", refName: "chr1", start, end, ref: "A", alt: ["T"], kind };
}

describe("VariantTrack", () => {
  it("renders a marker per visible variant with a descriptive title", () => {
    const wrapper = mount(VariantTrack, {
      props: { ...base, records: [variant("v1", 10, 11, "snv"), variant("v2", 30, 35, "del")] },
    });
    expect(wrapper.findAll("[data-variant-id]")).toHaveLength(2);
    expect(wrapper.find("polygon").exists()).toBe(true);
    expect(wrapper.find("rect").exists()).toBe(true);
    expect(wrapper.text()).toContain("A>T");
  });

  it("shows an empty state when nothing overlaps the view", () => {
    const wrapper = mount(VariantTrack, {
      props: { ...base, records: [variant("far", 500, 501, "snv")] },
    });
    expect(wrapper.findAll("[data-variant-id]")).toHaveLength(0);
    expect(wrapper.text()).toContain("No variants in view");
  });

  it("shows a loading state before records arrive", () => {
    const wrapper = mount(VariantTrack, { props: { ...base, loading: true } });
    expect(wrapper.text()).toContain("Loading variants");
  });
});
