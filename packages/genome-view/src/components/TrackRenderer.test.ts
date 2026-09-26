import { readFileSync } from "node:fs";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import {
  MemoryFileProvider,
  uriLocation,
  type AssemblyContext,
  type FileProvider,
  type TrackConfig,
} from "@soymutdb/genome-data";
import TrackRenderer from "./TrackRenderer.vue";

const fx = (name: string): Uint8Array =>
  new Uint8Array(readFileSync(new URL("../../../genome-data/test/fixtures/" + name, import.meta.url)));

const assemblies: AssemblyContext[] = [
  { key: "v4", name: "v4", refNames: ["chr01", "chr02"] },
];

/** Let the reader finish its promise chain (BAM header + index + range read). */
async function settle(): Promise<void> {
  await flushPromises();
  await new Promise((resolve) => setTimeout(resolve, 25));
  await flushPromises();
}

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

const BAM = uriLocation("mem://alignment.bam");
const BAI = uriLocation("mem://alignment.bam.bai");

function alignmentTrack(): TrackConfig {
  return {
    trackId: "alignments",
    name: "Read Alignments",
    type: "AlignmentsTrack",
    assemblyNames: ["v4"],
    adapter: {
      type: "BamAdapter",
      bamLocation: { uri: "mem://alignment.bam" },
      index: { indexType: "BAI", location: { uri: "mem://alignment.bam.bai" } },
    },
  };
}

function alignmentProvider(): MemoryFileProvider {
  const files = new MemoryFileProvider();
  files.add(BAM, fx("alignment.bam"));
  files.add(BAI, fx("alignment.bam.bai"));
  return files;
}

/** A provider whose reads always fail as if the caller aborted them. */
function abortingProvider(): FileProvider {
  return {
    open: async () => {
      const error = new Error("read aborted");
      error.name = "AbortError";
      throw error;
    },
  } as unknown as FileProvider;
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
    await settle();
    expect(wrapper.findAll("[data-variant-id]").length, wrapper.html()).toBeGreaterThan(0);
  });

  it("shows an error when no provider is configured", () => {
    const wrapper = mount(TrackRenderer, {
      props: { track: variantTrack(), assemblyKey: "v4", refName: "chr01", region: { start: 0, end: 60 } },
    });
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("No data provider");
  });

  it("renders AlignmentsTrack (not QuantitativeTrack) and maps records to read rects", async () => {
    const wrapper = mount(TrackRenderer, {
      props: {
        track: alignmentTrack(),
        assemblyKey: "v4",
        refName: "chr01",
        region: { start: 0, end: 60 },
        provider: alignmentProvider(),
        assemblies,
      },
    });
    await settle();
    // The alignment branch renders AlignmentsTrack; the generic quantitative
    // fallback must never catch this kind.
    expect(wrapper.find(".alignments-track").exists(), wrapper.html()).toBe(true);
    expect(wrapper.find(".quantitative-track").exists(), wrapper.html()).toBe(false);
    const reads = wrapper.findAll("[data-alignment-id]");
    expect(reads.length, wrapper.html()).toBe(3);
    expect(reads.map((read) => read.attributes("data-alignment-id"))).toEqual([
      "r1:chr01:0-5",
      "r2:chr01:9-14",
      "r3:chr01:19-24",
    ]);
  });

  it("surfaces a BamAdapter read failure and recovers through Retry", async () => {
    // The first read fails because the reference name is not yet resolvable.
    // resolveRegion throws before the BAM is opened, so the reader stays usable
    // and the inline Retry is the only thing that triggers a reload.
    const unresolved = [{ key: "v4", name: "v4", refNames: [] as string[] }];
    const wrapper = mount(TrackRenderer, {
      props: {
        track: alignmentTrack(),
        assemblyKey: "v4",
        refName: "chr01",
        region: { start: 0, end: 60 },
        provider: alignmentProvider(),
        assemblies: unresolved,
      },
    });
    await settle();
    expect(wrapper.find('[role="alert"]').exists(), wrapper.html()).toBe(true);
    expect(wrapper.text()).toContain('Unknown reference "chr01"');
    expect(wrapper.find(".track-renderer__retry").exists()).toBe(true);
    expect(wrapper.find(".alignments-track").exists()).toBe(false);

    // Publish the missing reference and retry in place; the same reader now
    // resolves chr01 and returns the reads.
    unresolved[0].refNames = ["chr01", "chr02"];
    await wrapper.find(".track-renderer__retry").trigger("click");
    await settle();
    expect(wrapper.find('[role="alert"]').exists(), wrapper.html()).toBe(false);
    expect(wrapper.findAll("[data-alignment-id]").length, wrapper.html()).toBe(3);
  });

  it("treats an aborted alignment read as a silent cancellation", async () => {
    const wrapper = mount(TrackRenderer, {
      props: {
        track: alignmentTrack(),
        assemblyKey: "v4",
        refName: "chr01",
        region: { start: 0, end: 60 },
        provider: abortingProvider(),
        assemblies,
      },
    });
    await settle();
    // Aborts follow the shared discipline: no error banner, no stale reads.
    expect(wrapper.find('[role="alert"]').exists(), wrapper.html()).toBe(false);
    expect(wrapper.find(".alignments-track").exists()).toBe(true);
    expect(wrapper.findAll("[data-alignment-id]")).toHaveLength(0);
    expect(wrapper.text()).toContain("No alignments in view");
  });
});
