import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import TrackRenderer from "../components/TrackRenderer.vue";
import { variantTrack } from "./support";

describe("ablation scenario 6: missing provider", () => {
  it("shows a role=alert error when no data provider is configured", () => {
    const wrapper = mount(TrackRenderer, {
      props: {
        track: variantTrack(),
        assemblyKey: "v4",
        refName: "chr01",
        region: { start: 0, end: 60 },
      },
    });
    const alert = wrapper.find('[role="alert"]');
    expect(alert.exists()).toBe(true);
    expect(alert.text()).toContain("No data provider");
    expect(wrapper.find(".track-renderer__retry").exists()).toBe(true);
  });
});
