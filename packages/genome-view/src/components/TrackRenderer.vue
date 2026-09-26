<template>
  <div class="track-renderer">
    <div v-if="displayError" class="track-renderer__error" role="alert">
      <p class="track-renderer__message">{{ displayError.message }}</p>
      <button class="track-renderer__retry" type="button" @click="load">Retry</button>
    </div>
    <template v-else-if="kind">
      <SequenceTrack
        v-if="kind === 'reference-sequence'"
        :track="props.track"
        :assembly-key="props.assemblyKey"
        :ref-name="props.refName"
        :chunks="sequenceChunks"
        :region="props.region"
        :width-px="props.widthPx"
        :loading="loading"
      />
      <VariantTrack
        v-else-if="kind === 'variant'"
        :track="props.track"
        :assembly-key="props.assemblyKey"
        :ref-name="props.refName"
        :records="variantRecords"
        :region="props.region"
        :width-px="props.widthPx"
        :loading="loading"
      />
      <FeatureTrack
        v-else-if="kind === 'feature' || kind === 'interval'"
        :track="props.track"
        :assembly-key="props.assemblyKey"
        :ref-name="props.refName"
        :records="featureRecords"
        :region="props.region"
        :width-px="props.widthPx"
        :loading="loading"
      />
      <QuantitativeTrack
        v-else
        :track="props.track"
        :assembly-key="props.assemblyKey"
        :ref-name="props.refName"
        :records="quantRecords"
        :region="props.region"
        :width-px="props.widthPx"
        :loading="loading"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import {
  createTrackDataSource,
  isAbortError,
  isGenomeDataError,
  GenomeDataError,
  type AssemblyContext,
  type FeatureRecord,
  type FileProvider,
  type QuantRecord,
  type Region,
  type SequenceChunk,
  type TrackConfig,
  type TrackDataSource,
  type VariantRecord,
} from "@soymutdb/genome-data";

import FeatureTrack from "./FeatureTrack.vue";
import QuantitativeTrack from "./QuantitativeTrack.vue";
import SequenceTrack from "./SequenceTrack.vue";
import VariantTrack from "./VariantTrack.vue";

const props = withDefaults(
  defineProps<{
    track: TrackConfig;
    assemblyKey: string;
    refName: string;
    region?: { start: number; end: number };
    widthPx?: number;
    provider?: FileProvider;
    assemblies?: readonly AssemblyContext[];
  }>(),
  { widthPx: 800 },
);

const sourceResult = computed<{ source: TrackDataSource | null; error: GenomeDataError | null }>(() => {
  if (!props.provider || !props.assemblies) {
    return {
      source: null,
      error: new GenomeDataError("unsupported-type", "No data provider is configured for this browser"),
    };
  }
  try {
    return {
      source: createTrackDataSource(props.track, {
        provider: props.provider,
        assemblies: props.assemblies,
      }),
      error: null,
    };
  } catch (error) {
    return {
      source: null,
      error: isGenomeDataError(error) ? error : new GenomeDataError("unsupported-type", String(error)),
    };
  }
});

const kind = computed(() => sourceResult.value.source?.kind);

const sequenceChunks = shallowRef<SequenceChunk[]>([]);
const variantRecords = shallowRef<VariantRecord[]>([]);
const featureRecords = shallowRef<FeatureRecord[]>([]);
const quantRecords = shallowRef<QuantRecord[]>([]);
const loading = ref(false);
const loadError = ref<Error | null>(null);

let controller: AbortController | null = null;

async function load(): Promise<void> {
  const source = sourceResult.value.source;
  if (!source || !props.region) return;
  controller?.abort();
  controller = new AbortController();
  const { signal } = controller;
  loading.value = true;
  loadError.value = null;
  const region: Region = {
    assemblyKey: props.assemblyKey,
    refName: props.refName,
    start: props.region.start,
    end: props.region.end,
  };
  try {
    switch (source.kind) {
      case "reference-sequence": {
        const next = await source.reader.getSequence(region, { signal });
        if (signal.aborted) return;
        sequenceChunks.value = [next];
        break;
      }
      case "variant": {
        const next = await source.reader.getVariants(region, { signal });
        if (signal.aborted) return;
        variantRecords.value = next;
        break;
      }
      case "feature":
      case "interval": {
        const next = await source.reader.getFeatures(region, { signal });
        if (signal.aborted) return;
        featureRecords.value = next;
        break;
      }
      case "quantitative": {
        const next = await source.reader.getQuantitative(region, { signal });
        if (signal.aborted) return;
        quantRecords.value = next;
        break;
      }
    }
  } catch (error) {
    if (isAbortError(error) || (isGenomeDataError(error) && error.code === "aborted")) return;
    loadError.value = error instanceof Error ? error : new Error(String(error));
    sequenceChunks.value = [];
    variantRecords.value = [];
    featureRecords.value = [];
    quantRecords.value = [];
  } finally {
    if (!signal.aborted) loading.value = false;
  }
}

watch(
  [sourceResult, () => props.region?.start, () => props.region?.end, () => props.refName],
  () => {
    void load();
  },
  { immediate: true },
);

onBeforeUnmount(() => controller?.abort());

const displayError = computed(() => sourceResult.value.error ?? (loading.value ? null : loadError.value));
</script>

<style scoped>
.track-renderer {
  position: relative;
  width: 100%;
}
.track-renderer__error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.375rem;
  padding: 0.75rem;
  border: 1px solid var(--destructive, oklch(0.58 0.22 27));
  border-radius: var(--radius-md, 0.625rem);
  background: color-mix(in oklch, var(--destructive, oklch(0.58 0.22 27)) 10%, transparent);
}
.track-renderer__message {
  margin: 0;
  font-size: var(--text-small, 0.875rem);
  line-height: var(--text-small--line-height, 1.55);
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
.track-renderer__retry {
  min-height: 2rem;
  padding-inline: 0.75rem;
  border: 1px solid var(--border, oklch(0.905 0.02 148));
  border-radius: var(--radius-md, 0.625rem);
  background: var(--card, #fff);
  color: var(--foreground, oklch(0.195 0.028 152));
  font-size: var(--text-small, 0.875rem);
  font-weight: 600;
  cursor: pointer;
}
.track-renderer__retry:focus-visible {
  outline: 2px solid var(--ring, oklch(0.55 0.14 152));
  outline-offset: 2px;
}
</style>
