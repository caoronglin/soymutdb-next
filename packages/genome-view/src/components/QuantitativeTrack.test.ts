import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { QuantRecord, TrackConfig } from "@soymutdb/genome-data";
import QuantitativeTrack from "./QuantitativeTrack.vue";

const track: TrackConfig = { trackId: "gc", name: "GC Content", type: "QuantitativeTrack", assemblyNames: ["v5"] };
const base = { track, assemblyKey: "v5", refName: "chr1", region: { start: 0, end: 100 }, widthPx: 100, heightPx: 60 };

function bin(id: string, start: number, end: number, score: number): QuantRecord {
  return { id, assemblyKey: "v5", refName: "chr1", start, end, score };
}

describe("QuantitativeTrack", () => {
  it("renders a bar per bin and scales height by the observed maximum", () => {
    const wrapper = mount(QuantitativeTrack, {
      props: { ...base, records: [bin("a", 0, 50, 10), bin("b", 50, 100, 5)] },
    });
    const bars = wrapper.findAll("[data-quant-id]");
    expect(bars).toHaveLength(2);
    expect(Number(bars[0].attributes("height"))).toBeGreaterThan(Number(bars[1].attributes("height")));
    expect(wrapper.text()).toContain("max 10");
  });

  it("shows an empty state when nothing overlaps the view", () => {
    const wrapper = mount(QuantitativeTrack, {
      props: { ...base, records: [bin("far", 500, 600, 3)] },
    });
    expect(wrapper.findAll("[data-quant-id]")).toHaveLength(0);
    expect(wrapper.text()).toContain("No data in view");
  });
});
