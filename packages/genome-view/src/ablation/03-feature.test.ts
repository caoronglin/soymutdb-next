import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { FeatureReader, uriLocation } from "@soymutdb/genome-data";
import TrackRenderer from "../components/TrackRenderer.vue";
import { ASSEMBLIES, FEATURE_FILES, featureTrack, memoryProvider, settle } from "./support";

describe("ablation scenario 3: feature track", () => {
  it("renders GFF3 features and preserves the parentId hierarchy", async () => {
    const provider = memoryProvider(FEATURE_FILES);
    const wrapper = mount(TrackRenderer, {
      props: {
        track: featureTrack(),
        assemblyKey: "v4",
        refName: "chr01",
        region: { start: 0, end: 60 },
        widthPx: 600,
        provider,
        assemblies: ASSEMBLIES,
      },
    });
    await settle();

    expect(wrapper.findAll(".feature-track__feature")).toHaveLength(5);
    expect(wrapper.html()).toContain("Gene01");

    const reader = new FeatureReader({
      provider,
      assembly: ASSEMBLIES[0],
      gff: uriLocation("mem://features.gff3.gz"),
      index: uriLocation("mem://features.gff3.gz.tbi"),
      trackId: "features",
    });
    const records = await reader.getFeatures({
      assemblyKey: "v4",
      refName: "chr01",
      start: 0,
      end: 60,
    });
    const byId = new Map(records.map((record) => [record.id, record]));
    expect(byId.get("gene01")?.parentId).toBeUndefined();
    expect(byId.get("mrna01")?.parentId).toBe("gene01");
    expect(byId.get("exon01")?.parentId).toBe("mrna01");
    expect(byId.get("cds01")?.parentId).toBe("mrna01");
    expect(byId.get("exon02")?.parentId).toBe("mrna01");
    expect(byId.get("gene01")?.start).toBe(0);
    expect(byId.get("gene01")?.end).toBe(60);
  });
});
