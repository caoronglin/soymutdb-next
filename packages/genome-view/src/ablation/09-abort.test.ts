import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import {
  VariantReader,
  isGenomeDataError,
  uriLocation,
  type FileProvider,
  type GenomeLocation,
  type Region,
  type VariantRecord,
} from "@soymutdb/genome-data";
import TrackRenderer from "../components/TrackRenderer.vue";
import { ASSEMBLIES, VARIANT_FILES, memoryProvider, settle, variantTrack } from "./support";

function readerFor(provider: FileProvider): VariantReader {
  return new VariantReader({
    provider,
    assembly: ASSEMBLIES[0],
    vcf: uriLocation("mem://variants.vcf.gz"),
    index: uriLocation("mem://variants.vcf.gz.tbi"),
    trackId: "variants",
  });
}

function record(id: string, start: number): VariantRecord {
  return {
    assemblyKey: "v4",
    refName: "chr01",
    start,
    end: start + 1,
    id,
    ref: "A",
    alt: ["T"],
    kind: "snv",
  };
}

describe("ablation scenario 9: abort", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("aborts the previous region's in-flight signal when the region changes", async () => {
    const signals: Array<AbortSignal | undefined> = [];
    vi.spyOn(VariantReader.prototype, "getVariants").mockImplementation(
      (_region: Region, options?: { signal?: AbortSignal }) => {
        signals.push(options?.signal);
        // Deliberately in flight forever; the component must still abort it.
        return new Promise<VariantRecord[]>(() => undefined);
      },
    );

    const wrapper = mount(TrackRenderer, {
      props: {
        track: variantTrack(),
        assemblyKey: "v4",
        refName: "chr01",
        region: { start: 0, end: 30 },
        provider: memoryProvider(VARIANT_FILES),
        assemblies: ASSEMBLIES,
      },
    });
    await nextTick();
    expect(signals).toHaveLength(1);
    expect(signals[0]?.aborted).toBe(false);

    await wrapper.setProps({ region: { start: 10, end: 30 } });
    await nextTick();
    await nextTick();
    expect(signals).toHaveLength(2);
    expect(signals[0]?.aborted).toBe(true);
    expect(signals[1]?.aborted).toBe(false);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("stops an in-flight tabix read when its signal is aborted", async () => {
    const inner = memoryProvider(VARIANT_FILES);
    const slow: FileProvider = {
      async open(location: GenomeLocation) {
        await new Promise((resolvePromise) => setTimeout(resolvePromise, 40));
        return inner.open(location);
      },
    };
    const reader = readerFor(slow);
    const controller = new AbortController();
    const pending = reader.getVariants(
      { assemblyKey: "v4", refName: "chr01", start: 0, end: 60 },
      { signal: controller.signal },
    );
    setTimeout(() => controller.abort(), 5);

    let outcome: string;
    try {
      const records = await pending;
      outcome = "resolved:" + records.length;
    } catch (error) {
      outcome = "rejected:" + (isGenomeDataError(error) ? error.code : "unknown");
    }
    expect(controller.signal.aborted).toBe(true);
    expect(outcome).toBe("rejected:aborted");
  });

  it("does not render a stale result that resolves after the newer region", async () => {
    const deferred: Array<(records: VariantRecord[]) => void> = [];
    vi.spyOn(VariantReader.prototype, "getVariants").mockImplementation((_region: Region) => {
      return new Promise<VariantRecord[]>((resolve) => {
        deferred.push(resolve);
      });
    });

    const wrapper = mount(TrackRenderer, {
      props: {
        track: variantTrack(),
        assemblyKey: "v4",
        refName: "chr01",
        region: { start: 0, end: 30 },
        provider: memoryProvider(VARIANT_FILES),
        assemblies: ASSEMBLIES,
      },
    });
    await nextTick();
    await wrapper.setProps({ region: { start: 5, end: 30 } });
    await nextTick();
    expect(deferred).toHaveLength(2);

    deferred[1]([record("new-region", 20)]);
    await settle();
    expect(wrapper.find('[data-variant-id="new-region"]').exists()).toBe(true);

    deferred[0]([record("stale-region", 6)]);
    await settle();
    expect(wrapper.find('[data-variant-id="stale-region"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
