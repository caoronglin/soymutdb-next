import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { AlignmentRecord, TrackConfig } from "@soymutdb/genome-data";
import AlignmentsTrack from "./AlignmentsTrack.vue";

const track: TrackConfig = {
  trackId: "alignments",
  name: "Read alignments",
  type: "AlignmentsTrack",
  assemblyNames: ["v5"],
};
const base = { track, assemblyKey: "v5", refName: "chr1", region: { start: 0, end: 100 }, widthPx: 100 };

function read(
  id: string,
  start: number,
  end: number,
  strand: "+" | "-" = "+",
  mapq = 60,
  cigar = "50M",
): AlignmentRecord {
  return { id, assemblyKey: "v5", refName: "chr1", start, end, readName: id, read: "ACGT", strand, mapq, cigar };
}

describe("AlignmentsTrack", () => {
  it("renders one block per visible read with a coverage histogram and metadata title", () => {
    const wrapper = mount(AlignmentsTrack, {
      props: { ...base, records: [read("r1", 0, 20), read("r2", 40, 60, "-", 30, "20M")] },
    });
    expect(wrapper.findAll("[data-alignment-id]")).toHaveLength(2);
    expect(wrapper.findAll(".alignments-track__coverage-bar").length).toBeGreaterThan(0);
    const titles = wrapper.findAll("[data-alignment-id] title").map((node) => node.text());
    expect(titles[0]).toContain("r1");
    expect(titles[0]).toContain("chr1:1-20");
    expect(titles[0]).toContain("MAPQ 60");
    expect(titles[0]).toContain("50M");
    expect(wrapper.find("svg").attributes("role")).toBe("img");
    expect(wrapper.find("svg").attributes("aria-label")).toContain("chr1");
  });

  it("colours forward and reverse reads differently", () => {
    const wrapper = mount(AlignmentsTrack, {
      props: { ...base, records: [read("fwd", 0, 20, "+"), read("rev", 40, 60, "-")] },
    });
    const forward = wrapper.find('[data-alignment-id="fwd"]').attributes("fill");
    const reverse = wrapper.find('[data-alignment-id="rev"]').attributes("fill");
    expect(forward).toBeTruthy();
    expect(reverse).toBeTruthy();
    expect(forward).not.toBe(reverse);
  });

  it("drops reads outside the region and shows the empty state", () => {
    const wrapper = mount(AlignmentsTrack, {
      props: { ...base, records: [read("far", 500, 520)] },
    });
    expect(wrapper.findAll("[data-alignment-id]")).toHaveLength(0);
    expect(wrapper.text()).toContain("No alignments in view");
  });

  it("shows the loading state before records arrive", () => {
    const wrapper = mount(AlignmentsTrack, { props: { ...base, loading: true } });
    expect(wrapper.find("[role='status']").text()).toContain("Loading alignments");
    expect(wrapper.find("svg").exists()).toBe(false);
  });
});
