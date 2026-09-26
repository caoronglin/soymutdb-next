import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import TrackRenderer from "../components/TrackRenderer.vue";
import { ASSEMBLIES, SEQUENCE_FILES, memoryProvider, referenceTrack, settle } from "./support";

describe("ablation scenario 1: reference sequence track", () => {
  it("renders bases from reference.fa.gz/.fai/.gzi through TrackRenderer", async () => {
    const wrapper = mount(TrackRenderer, {
      props: {
        track: referenceTrack(),
        assemblyKey: "v4",
        refName: "chr01",
        region: { start: 0, end: 12 },
        widthPx: 200,
        provider: memoryProvider(SEQUENCE_FILES),
        assemblies: ASSEMBLIES,
      },
    });
    await settle();
    const bases = wrapper
      .findAll("[data-base]")
      .map((node) => node.attributes("data-base"))
      .join("");
    expect(bases).toBe("ACGTACGTACGT");
    expect(wrapper.find(".sequence-track__bases").exists()).toBe(true);
  });
});
