<template>
  <div class="sequence-track" :data-track-id="props.track.trackId">
    <p v-if="props.loading" class="sequence-track__state" role="status">Loading sequence...</p>
    <p v-else-if="bases.length === 0" class="sequence-track__state">No sequence in view</p>
    <p v-else-if="tooDense" class="sequence-track__state">
      Zoom in to read the sequence ({{ bases.length }} bp)
    </p>
    <div v-else class="sequence-track__bases" role="img" :aria-label="ariaLabel">
      <span
        v-for="(base, index) in bases"
        :key="index"
        class="sequence-track__base"
        :class="'sequence-track__base--' + base.toLowerCase()"
        :data-base="base"
      >{{ base }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { SequenceChunk, TrackConfig } from "@soymutdb/genome-data";

const props = withDefaults(
  defineProps<{
    track: TrackConfig;
    assemblyKey: string;
    refName: string;
    chunks?: SequenceChunk[];
    region?: { start: number; end: number };
    widthPx?: number;
    loading?: boolean;
  }>(),
  { chunks: () => [], widthPx: 800, loading: false },
);

const MIN_PX_PER_BASE = 8;

const bases = computed(() => props.chunks.map((chunk) => chunk.bases).join("").toUpperCase());
const tooDense = computed(() => bases.value.length > props.widthPx / MIN_PX_PER_BASE);
const ariaLabel = computed(
  () => props.track.name + " sequence, " + bases.value.length + " bases on " + props.refName,
);
</script>

<style scoped>
.sequence-track {
  position: relative;
  width: 100%;
}
.sequence-track__bases {
  display: flex;
  flex-wrap: wrap;
  gap: 1px;
  padding: 0.5rem;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.8125rem;
  letter-spacing: 0.05em;
}
.sequence-track__base {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-inline-size: 1.25rem;
  block-size: 1.5rem;
  border-radius: 3px;
  background: var(--muted, oklch(0.968 0.012 148));
  color: var(--foreground, oklch(0.195 0.028 152));
}
.sequence-track__base--a { color: oklch(0.52 0.16 150); }
.sequence-track__base--t { color: oklch(0.55 0.18 27); }
.sequence-track__base--g { color: oklch(0.58 0.14 65); }
.sequence-track__base--c { color: oklch(0.55 0.13 240); }
.sequence-track__state {
  margin: 0;
  padding: 1rem;
  text-align: center;
  font-size: 0.8125rem;
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
</style>
