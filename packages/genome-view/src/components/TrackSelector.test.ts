import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { TrackConfig } from "@soymutdb/genome-data";
import TrackSelector from "./TrackSelector.vue";

function trackConfig(trackId: string): TrackConfig {
  return { trackId, name: "Track " + trackId, type: "FeatureTrack", assemblyNames: ["v5"] };
}

describe("TrackSelector", () => {
  it("renders one checkbox per track and reflects the selection", () => {
    const wrapper = mount(TrackSelector, {
      props: {
        tracks: [trackConfig("a"), trackConfig("b")],
        modelValue: ["b"],
      },
    });
    const boxes = wrapper.findAll('input[type="checkbox"]');
    expect(boxes).toHaveLength(2);
    expect((boxes[0].element as HTMLInputElement).checked).toBe(false);
    expect((boxes[1].element as HTMLInputElement).checked).toBe(true);
  });

  it("emits the next selection when a track is toggled", async () => {
    const wrapper = mount(TrackSelector, {
      props: { tracks: [trackConfig("a"), trackConfig("b")], modelValue: [] },
    });
    const boxes = wrapper.findAll('input[type="checkbox"]');
    await boxes[0].setValue(true);
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([["a"]]);
    // Controlled prop: reflect the emitted selection before the next toggle.
    await wrapper.setProps({ modelValue: ["a"] });
    await boxes[1].setValue(true);
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([["a", "b"]]);
  });

  it("shows an empty state when there are no tracks", () => {
    const wrapper = mount(TrackSelector, { props: { tracks: [], modelValue: [] } });
    expect(wrapper.text()).toContain("No tracks available");
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(0);
  });
});
