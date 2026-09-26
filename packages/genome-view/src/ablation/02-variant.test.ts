import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { VariantReader, uriLocation } from "@soymutdb/genome-data";
import TrackRenderer from "../components/TrackRenderer.vue";
import { ASSEMBLIES, VARIANT_FILES, memoryProvider, settle, variantTrack } from "./support";

const SNV_ID = "rs1";
const DEL_ID = "chr01:4-8:ACGT>A";
const SV_ID = "chr01:19-40:N><DEL>";
const BREAKEND_ID = "chr01:49-50:N>N]chr02:30]";

describe("ablation scenario 2: variant track", () => {
  it("renders VCF markers and classifies snv/del/sv correctly", async () => {
    const provider = memoryProvider(VARIANT_FILES);
    const wrapper = mount(TrackRenderer, {
      props: {
        track: variantTrack(),
        assemblyKey: "v4",
        refName: "chr01",
        region: { start: 0, end: 60 },
        widthPx: 600,
        provider,
        assemblies: ASSEMBLIES,
      },
    });
    await settle();

    const ids = wrapper.findAll("[data-variant-id]").map((node) => node.attributes("data-variant-id"));
    expect(ids).toHaveLength(6);
    const tag = (id: string) =>
      wrapper.find('[data-variant-id="' + id + '"]').element.tagName.toLowerCase();
    expect(tag(SNV_ID)).toBe("polygon");
    expect(tag(DEL_ID)).toBe("rect");
    expect(tag(SV_ID)).toBe("rect");
    expect(tag(BREAKEND_ID)).toBe("rect");

    const legend = wrapper.findAll(".variant-track__legend-item").map((node) => node.text());
    expect(legend).toEqual(expect.arrayContaining(["snv", "del", "ins", "mnv", "sv"]));

    // Independent classification check against the real VariantReader.
    const reader = new VariantReader({
      provider,
      assembly: ASSEMBLIES[0],
      vcf: uriLocation("mem://variants.vcf.gz"),
      index: uriLocation("mem://variants.vcf.gz.tbi"),
      trackId: "variants",
    });
    const records = await reader.getVariants({
      assemblyKey: "v4",
      refName: "chr01",
      start: 0,
      end: 60,
    });
    const kindById = new Map(records.map((record) => [record.id, record.kind]));
    expect(kindById.get(SNV_ID)).toBe("snv");
    expect(kindById.get(DEL_ID)).toBe("del");
    expect(kindById.get(SV_ID)).toBe("sv");
    expect(kindById.get(BREAKEND_ID)).toBe("sv");
  });
});
