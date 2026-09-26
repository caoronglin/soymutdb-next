import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { flushPromises } from "@vue/test-utils";
import {
  MemoryFileProvider,
  uriLocation,
  type AssemblyContext,
  type TrackConfig,
} from "@soymutdb/genome-data";

/** Committed genome-data fixtures only; the ablation never touches the network. */
const FIXTURE_DIR = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../genome-data/test/fixtures",
);

export function fixtureBytes(name: string): Uint8Array {
  return new Uint8Array(readFileSync(resolve(FIXTURE_DIR, name)));
}

export const ASSEMBLIES: readonly AssemblyContext[] = [
  { key: "v4", name: "v4", refNames: ["chr01", "chr02"] },
  { key: "v5", name: "v5", refNames: ["chr1", "chr2"] },
];

export function memoryProvider(names: readonly string[]): MemoryFileProvider {
  const provider = new MemoryFileProvider();
  for (const name of names) provider.add(uriLocation("mem://" + name), fixtureBytes(name));
  return provider;
}

export const SEQUENCE_FILES = ["reference.fa.gz", "reference.fa.gz.fai", "reference.fa.gz.gzi"];
export const VARIANT_FILES = ["variants.vcf.gz", "variants.vcf.gz.tbi"];
export const FEATURE_FILES = ["features.gff3.gz", "features.gff3.gz.tbi"];

export function referenceTrack(): TrackConfig {
  return {
    trackId: "reference",
    name: "Reference sequence",
    type: "ReferenceSequenceTrack",
    assemblyNames: ["v4"],
    adapter: {
      type: "BgzipFastaAdapter",
      fastaLocation: { uri: "mem://reference.fa.gz" },
      faiLocation: { uri: "mem://reference.fa.gz.fai" },
      gziLocation: { uri: "mem://reference.fa.gz.gzi" },
    },
  };
}

export function variantTrack(): TrackConfig {
  return {
    trackId: "variants",
    name: "SNPs and indels",
    type: "VariantTrack",
    assemblyNames: ["v4"],
    adapter: {
      type: "VcfTabixAdapter",
      vcfGzLocation: { uri: "mem://variants.vcf.gz" },
      index: { uri: "mem://variants.vcf.gz.tbi" },
    },
  };
}

export function featureTrack(): TrackConfig {
  return {
    trackId: "features",
    name: "Gene models",
    type: "FeatureTrack",
    assemblyNames: ["v4"],
    adapter: {
      type: "Gff3TabixAdapter",
      gffGzLocation: { uri: "mem://features.gff3.gz" },
      index: { uri: "mem://features.gff3.gz.tbi" },
    },
  };
}

export function bigBedFeatureTrack(): TrackConfig {
  return {
    trackId: "repeats",
    name: "Repeats",
    type: "FeatureTrack",
    assemblyNames: ["v4"],
    adapter: { type: "BigBedAdapter", bigBedLocation: { uri: "mem://repeats.bb" } },
  };
}

export function quantitativeTrack(): TrackConfig {
  return {
    trackId: "coverage",
    name: "Coverage",
    type: "QuantitativeTrack",
    assemblyNames: ["v4"],
    adapter: { type: "BigWigAdapter", bigWigLocation: { uri: "mem://coverage.bw" } },
  };
}

/** Flush Vue's microtasks plus any async reader I/O kicked off by a watcher. */
export async function settle(ms = 30): Promise<void> {
  await flushPromises();
  await new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
  await flushPromises();
}
