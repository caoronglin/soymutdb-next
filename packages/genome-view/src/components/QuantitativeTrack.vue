<template>
  <div class="quantitative-track" :data-track-id="props.track.trackId">
    <p v-if="props.loading" class="quantitative-track__state" role="status">Loading track...</p>
    <p v-else-if="bars.length === 0" class="quantitative-track__state">No data in view</p>
    <svg
      v-else
      class="quantitative-track__svg"
      :width="props.widthPx"
      :height="props.heightPx"
      :viewBox="viewBox"
      role="img"
      :aria-label="ariaLabel"
    >
      <line
        class="quantitative-track__baseline"
        x1="0"
        :y1="props.heightPx"
        :x2="props.widthPx"
        :y2="props.heightPx"
      />
      <rect
        v-for="bar in bars"
        :key="bar.id"
        class="quantitative-track__bar"
        :data-quant-id="bar.id"
        :x="bar.x"
        :y="bar.y"
        :width="bar.w"
        :height="bar.h"
      >
        <title>{{ bar.title }}</title>
      </rect>
      <text class="quantitative-track__max" x="4" y="12">{{ maxLabel }}</text>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { QuantRecord, TrackConfig } from "@soymutdb/genome-data";

import { clipToRegion, type RegionLike } from "../track-layout";

const props = withDefaults(
  defineProps<{
    track: TrackConfig;
    assemblyKey: string;
    refName: string;
    records?: QuantRecord[];
    region?: RegionLike;
    widthPx?: number;
    heightPx?: number;
    maxScore?: number;
    loading?: boolean;
  }>(),
  { records: () => [], widthPx: 800, heightPx: 64, loading: false },
);

const region = computed<RegionLike>(() => {
  if (props.region) return props.region;
  if (props.records.length === 0) return { start: 0, end: 1 };
  let start = Number.POSITIVE_INFINITY;
  let end = Number.NEGATIVE_INFINITY;
  for (const record of props.records) {
    start = Math.min(start, record.start);
    end = Math.max(end, record.end);
  }
  return { start, end: end > start ? end : start + 1 };
});

const scale = computed(() => props.widthPx / (region.value.end - region.value.start));
const maxValue = computed(() => {
  if (props.maxScore !== undefined && props.maxScore > 0) return props.maxScore;
  const observed = props.records.reduce((max, record) => Math.max(max, record.score), 0);
  return observed > 0 ? observed : 1;
});

interface Bar {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
}

const bars = computed<Bar[]>(() => {
  const result: Bar[] = [];
  for (const record of props.records) {
    const clipped = clipToRegion({ start: record.start, end: record.end }, region.value);
    if (!clipped) continue;
    const x = (clipped.start - region.value.start) * scale.value;
    const w = Math.max(1, (clipped.end - clipped.start) * scale.value);
    const h = Math.max(0, (record.score / maxValue.value) * (props.heightPx - 4));
    result.push({
      id: record.id ?? record.start + "-" + record.end,
      x,
      y: props.heightPx - h,
      w,
      h,
      title: props.refName + ":" + (record.start + 1) + " = " + record.score,
    });
  }
  return result;
});

const viewBox = computed(() => "0 0 " + props.widthPx + " " + props.heightPx);
const maxLabel = computed(() => "max " + maxValue.value);
const ariaLabel = computed(
  () => props.track.name + " (" + bars.value.length + " bins, max " + maxValue.value + ")",
);
</script>

<style scoped>
.quantitative-track {
  position: relative;
  width: 100%;
}
.quantitative-track__svg {
  display: block;
  max-width: 100%;
}
.quantitative-track__bar {
  fill: var(--chart-1, oklch(0.55 0.14 152));
  opacity: 0.85;
}
.quantitative-track__bar:hover {
  opacity: 1;
}
.quantitative-track__baseline {
  stroke: var(--border, oklch(0.905 0.02 148));
  stroke-width: 1;
}
.quantitative-track__max {
  fill: var(--muted-foreground, oklch(0.48 0.028 152));
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: var(--text-caption, 0.75rem);
}
.quantitative-track__state {
  margin: 0;
  padding: 1rem;
  text-align: center;
  font-size: var(--text-small, 0.875rem);
  line-height: var(--text-small--line-height, 1.55);
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
</style>
