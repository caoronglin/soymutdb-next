import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TrackConfig } from "@soymutdb/genome-data";
import { registerTrackRenderer } from "../registry";
import GenomeBrowser from "./GenomeBrowser.vue";

const RecordingTrack = defineComponent({
  name: "RecordingTrack",
  props: {
    track: { type: Object, required: true },
    assemblyKey: { type: String, required: true },
    refName: { type: String, required: true },
  },
  setup(props) {
    return () =>
      h("div", {
        class: "recording-track",
        "data-track-id": (props.track as TrackConfig).trackId,
        "data-assembly": props.assemblyKey,
        "data-ref": props.refName,
      });
  },
});

registerTrackRenderer("TestBrowserKnownTrack", { component: RecordingTrack });

function trackConfig(trackId: string, type: string): TrackConfig {
  return { trackId, name: trackId, type, assemblyNames: ["v5"] };
}

describe("GenomeBrowser", () => {
  const warnings: string[] = [];

  beforeEach(() => {
    warnings.length = 0;
    vi.spyOn(console, "warn").mockImplementation((...args: unknown[]) => {
      warnings.push(args.map((arg) => String(arg)).join(" "));
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a ruler strip and resolves known tracks through the registry", () => {
    const wrapper = mount(GenomeBrowser, {
      props: {
        assemblyKey: "v5",
        refName: "chr1",
        tracks: [trackConfig("known-1", "TestBrowserKnownTrack")],
      },
    });
    expect(wrapper.find('[data-testid="genome-ruler"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="genome-tracks"]').exists()).toBe(true);
    const rendered = wrapper.find(".recording-track");
    expect(rendered.attributes("data-track-id")).toBe("known-1");
    expect(rendered.attributes("data-assembly")).toBe("v5");
    expect(rendered.attributes("data-ref")).toBe("chr1");
  });

  it("skips unknown track types and warns only once per type", async () => {
    const wrapper = mount(GenomeBrowser, {
      props: {
        assemblyKey: "v5",
        refName: "chr1",
        tracks: [
          trackConfig("known-1", "TestBrowserKnownTrack"),
          trackConfig("unknown-1", "TestBrowserUnknownTrack"),
          trackConfig("unknown-2", "TestBrowserUnknownTrack"),
        ],
      },
    });
    expect(wrapper.findAll(".recording-track")).toHaveLength(1);
    expect(warnings.filter((line) => line.includes("TestBrowserUnknownTrack"))).toHaveLength(1);

    await wrapper.setProps({
      tracks: [
        trackConfig("known-1", "TestBrowserKnownTrack"),
        trackConfig("unknown-3", "TestBrowserUnknownTrack"),
      ],
    });
    expect(warnings.filter((line) => line.includes("TestBrowserUnknownTrack"))).toHaveLength(1);
  });

  it("warns once for each distinct unknown type", () => {
    mount(GenomeBrowser, {
      props: {
        assemblyKey: "v5",
        refName: "chr1",
        tracks: [
          trackConfig("unknown-a", "TestBrowserUnknownA"),
          trackConfig("unknown-b", "TestBrowserUnknownB"),
        ],
      },
    });
    expect(warnings.filter((line) => line.includes("TestBrowserUnknownA"))).toHaveLength(1);
    expect(warnings.filter((line) => line.includes("TestBrowserUnknownB"))).toHaveLength(1);
  });
});
