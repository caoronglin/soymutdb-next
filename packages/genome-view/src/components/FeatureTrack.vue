<template>
  <div class="feature-track" :data-track-id="props.track.trackId">
    <p v-if="props.loading" class="feature-track__state" role="status">Loading features...</p>
    <p v-else-if="placed.length === 0" class="feature-track__state">No features in view</p>
    <svg
      v-else
      class="feature-track__svg"
      :width="widthPx"
      :height="heightPx"
      :viewBox="viewBox"
      role="img"
      :aria-label="ariaLabel"
    >
      <g v-for="item in placed" :key="item.id" :transform="translate(item)">
        <rect
          class="feature-track__feature"
          :width="item.w"
          :height="rowHeight - ROW_GAP"
          rx="2"
          :fill="fillFor(strandOf(item.id))"
        >
          <title>{{ titleOf(item.id) }}</title>
        </rect>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { FeatureRecord, TrackConfig } from "@soymutdb/genome-data";

import { layoutIntervals, type RegionLike } from "../track-layout";

const props = withDefaults(
  defineProps<{
    track: TrackConfig;
    assemblyKey: string;
    refName: string;
    records?: FeatureRecord[];
    region?: RegionLike;
    widthPx?: number;
    rowHeight?: number;
    loading?: boolean;
  }>(),
  { records: () => [], widthPx: 800, rowHeight: 18, loading: false },
);

const ROW_GAP = 6;

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

const byId = computed(() => new Map(props.records.map((record) => [record.id, record])));

const layout = computed(() =>
  layoutIntervals(props.records, region.value, props.widthPx, { gapPx: 2 }),
);

const placed = computed(() => layout.value.placed);
const heightPx = computed(() => Math.max(props.rowHeight, layout.value.rowCount * props.rowHeight));
const viewBox = computed(() => "0 0 " + props.widthPx + " " + heightPx.value);
const ariaLabel = computed(
  () => props.track.name + " (" + placed.value.length + " features on " + props.refName + ")",
);

function strandOf(id: string): string | undefined {
  return byId.value.get(id)?.strand;
}

function fillFor(strand: string | undefined): string {
  if (strand === "-") return "var(--chart-2, oklch(0.66 0.12 150))";
  if (strand === "+") return "var(--primary, oklch(0.46 0.13 152))";
  return "var(--muted-foreground, oklch(0.48 0.028 152))";
}

function translate(item: { x: number; w: number; row: number }): string {
  return "translate(" + item.x + "," + item.row * props.rowHeight + ")";
}

function titleOf(id: string): string {
  const record = byId.value.get(id);
  if (!record) return id;
  const start = record.start + 1;
  return (record.name ?? record.id) + " " + props.refName + ":" + start + "-" + record.end;
}
</script>

<style scoped>
.feature-track {
  position: relative;
  width: 100%;
}
.feature-track__svg {
  display: block;
  max-width: 100%;
}
.feature-track__feature {
  opacity: 0.9;
}
.feature-track__feature:hover {
  opacity: 1;
}
.feature-track__state {
  margin: 0;
  padding: 1rem;
  text-align: center;
  font-size: 0.8125rem;
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
</style>
