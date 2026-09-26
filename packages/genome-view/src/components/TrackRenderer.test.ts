import { readFileSync } from "node:fs";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import {
  MemoryFileProvider,
  uriLocation,
  type AssemblyContext,
  type TrackConfig,
} from "@soymutdb/genome-data";
import TrackRenderer from "./TrackRenderer.vue";

const fx = (name: string): Uint8Array =>
  new Uint8Array(readFileSync(new URL("../../../genome-data/test/fixtures/" + name, import.meta.url)));

const assemblies: AssemblyContext[] = [
  { key: "v4", name: "v4", refNames: ["chr01", "chr02"] },
];

function variantTrack(): TrackConfig {
  return {
    trackId: "variants",
    name: "SNPs & Indels",
    type: "VariantTrack",
    assemblyNames: ["v4"],
    adapter: {
      type: "VcfTabixAdapter",
      vcfGzLocation: { uri: "mem://variants.vcf.gz" },
      index: { uri: "mem://variants.vcf.gz.tbi" },
    },
  };
}

function provider(): MemoryFileProvider {
  const files = new MemoryFileProvider();
  files.add(uriLocation("mem://variants.vcf.gz"), fx("variants.vcf.gz"));
  files.add(uriLocation("mem://variants.vcf.gz.tbi"), fx("variants.vcf.gz.tbi"));
  return files;
}

describe("TrackRenderer", () => {
  it("loads records for the region and renders the variant track", async () => {
    const wrapper = mount(TrackRenderer, {
      props: {
        track: variantTrack(),
        assemblyKey: "v4",
        refName: "chr01",
        region: { start: 0, end: 60 },
        provider: provider(),
        assemblies,
      },
    });
    await flushPromises();
    await new Promise((resolve) => setTimeout(resolve, 25));
    await flushPromises();
    expect(wrapper.findAll("[data-variant-id]").length, wrapper.html()).toBeGreaterThan(0);
  });

  it("shows an error when no provider is configured", () => {
    const wrapper = mount(TrackRenderer, {
      props: { track: variantTrack(), assemblyKey: "v4", refName: "chr01", region: { start: 0, end: 60 } },
    });
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("No data provider");
  });
});
