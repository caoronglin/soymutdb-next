import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TrackConfig } from "@soymutdb/genome-data";
import { registerTrackRenderer, resolveTrackRenderer } from "../registry";
import GenomeBrowser from "../components/GenomeBrowser.vue";

const KNOWN_TYPE = "AblationKnownTrack";
const UNKNOWN_A = "AblationUnknownTrackA";
const UNKNOWN_B = "AblationUnknownTrackB";

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
      });
  },
});

if (!resolveTrackRenderer(KNOWN_TYPE)) {
  registerTrackRenderer(KNOWN_TYPE, { component: RecordingTrack });
}

function trackConfig(trackId: string, type: string): TrackConfig {
  return { trackId, name: trackId, type, assemblyNames: ["v5"] };
}

describe("ablation scenario 5: unknown track type", () => {
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

  it("skips unknown types and warns exactly once per type per mount", () => {
    const wrapper = mount(GenomeBrowser, {
      props: {
        assemblyKey: "v5",
        refName: "chr1",
        tracks: [
          trackConfig("known-1", KNOWN_TYPE),
          trackConfig("unknown-1a", UNKNOWN_A),
          trackConfig("unknown-1b", UNKNOWN_A),
          trackConfig("unknown-2", UNKNOWN_B),
        ],
      },
    });
    expect(wrapper.findAll(".recording-track")).toHaveLength(1);
    expect(warnings.filter((line) => line.includes(UNKNOWN_A))).toHaveLength(1);
    expect(warnings.filter((line) => line.includes(UNKNOWN_B))).toHaveLength(1);
    wrapper.unmount();
  });

  it("warns again once per new mount and renders no blank track", () => {
    const first = mount(GenomeBrowser, {
      props: {
        assemblyKey: "v5",
        refName: "chr1",
        tracks: [trackConfig("u1", UNKNOWN_A), trackConfig("u2", UNKNOWN_A)],
      },
    });
    expect(warnings.filter((line) => line.includes(UNKNOWN_A))).toHaveLength(1);
    expect(first.find(".recording-track").exists()).toBe(false);
    expect(first.find(".genome-browser__empty").exists()).toBe(true);
    first.unmount();

    warnings.length = 0;
    const second = mount(GenomeBrowser, {
      props: {
        assemblyKey: "v5",
        refName: "chr1",
        tracks: [trackConfig("u3", UNKNOWN_A)],
      },
    });
    expect(warnings.filter((line) => line.includes(UNKNOWN_A))).toHaveLength(1);
    second.unmount();
  });
});
