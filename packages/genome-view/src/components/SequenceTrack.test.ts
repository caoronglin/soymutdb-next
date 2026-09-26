import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { SequenceChunk, TrackConfig } from "@soymutdb/genome-data";
import SequenceTrack from "./SequenceTrack.vue";

const track: TrackConfig = { trackId: "ref", name: "Reference Sequence", type: "ReferenceSequenceTrack", assemblyNames: ["v5"] };
const base = { track, assemblyKey: "v5", refName: "chr1", widthPx: 400 };

function chunk(bases: string): SequenceChunk {
  return { assemblyKey: "v5", refName: "chr1", start: 0, bases };
}

describe("SequenceTrack", () => {
  it("renders one span per base when there is room", () => {
    const wrapper = mount(SequenceTrack, { props: { ...base, chunks: [chunk("ACGT")] } });
    expect(wrapper.findAll(".sequence-track__base")).toHaveLength(4);
    expect(wrapper.find('[data-base="A"]').text()).toBe("A");
  });

  it("asks the user to zoom in when bases are too dense", () => {
    const wrapper = mount(SequenceTrack, { props: { ...base, chunks: [chunk("A".repeat(200))] } });
    expect(wrapper.text()).toContain("Zoom in");
    expect(wrapper.findAll(".sequence-track__base")).toHaveLength(0);
  });

  it("shows empty and loading states", () => {
    expect(mount(SequenceTrack, { props: base }).text()).toContain("No sequence in view");
    expect(mount(SequenceTrack, { props: { ...base, loading: true } }).text()).toContain("Loading sequence");
  });
});
