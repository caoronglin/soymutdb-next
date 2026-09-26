<template>
  <div class="variant-track" :data-track-id="props.track.trackId">
    <p v-if="props.loading" class="variant-track__state" role="status">Loading variants...</p>
    <p v-else-if="marks.length === 0" class="variant-track__state">No variants in view</p>
    <template v-else>
      <svg
        class="variant-track__svg"
        :width="props.widthPx"
        :height="props.heightPx"
        :viewBox="viewBox"
        role="img"
        :aria-label="ariaLabel"
      >
        <g v-for="mark in marks" :key="mark.id">
          <rect
            v-if="mark.kind === 'del' || mark.kind === 'sv'"
            :data-variant-id="mark.id"
            :x="mark.x"
            :y="midY - MARK_SIZE / 2"
            :width="mark.w"
            :height="MARK_SIZE"
            :fill="fillFor(mark.kind)"
          >
            <title>{{ mark.title }}</title>
          </rect>
          <polygon
            v-else
            :data-variant-id="mark.id"
            :points="diamond(mark.x)"
            :fill="fillFor(mark.kind)"
          >
            <title>{{ mark.title }}</title>
          </polygon>
        </g>
      </svg>
      <ul class="variant-track__legend">
        <li v-for="kind in presentKinds" :key="kind" class="variant-track__legend-item">
          <span class="variant-track__swatch" :style="{ backgroundColor: fillFor(kind) }" aria-hidden="true" />
          {{ kind }}
        </li>
      </ul>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { TrackConfig, VariantRecord } from "@soymutdb/genome-data";

import { clipToRegion, type RegionLike } from "../track-layout";

const props = withDefaults(
  defineProps<{
    track: TrackConfig;
    assemblyKey: string;
    refName: string;
    records?: VariantRecord[];
    region?: RegionLike;
    widthPx?: number;
    heightPx?: number;
    loading?: boolean;
  }>(),
  { records: () => [], widthPx: 800, heightPx: 48, loading: false },
);

const MARK_SIZE = 9;

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
const midY = computed(() => props.heightPx / 2);

interface Mark {
  id: string;
  kind: VariantRecord["kind"];
  x: number;
  w: number;
  title: string;
}

const marks = computed<Mark[]>(() => {
  const result: Mark[] = [];
  for (const record of props.records) {
    const clipped = clipToRegion({ start: record.start, end: record.end }, region.value);
    if (!clipped) continue;
    const x = (clipped.start - region.value.start) * scale.value;
    const w = Math.max(MARK_SIZE, (clipped.end - clipped.start) * scale.value);
    result.push({
      id: record.id,
      kind: record.kind,
      x,
      w,
      title:
        props.refName + ":" + (record.start + 1) + " " + record.ref + ">" + record.alt.join(","),
    });
  }
  return result;
});

const presentKinds = computed(() => [...new Set(marks.value.map((mark) => mark.kind))]);
const viewBox = computed(() => "0 0 " + props.widthPx + " " + props.heightPx);
const ariaLabel = computed(
  () => props.track.name + " (" + marks.value.length + " variants on " + props.refName + ")",
);

function diamond(x: number): string {
  const half = MARK_SIZE / 2;
  const cy = midY.value;
  return (x - half) + "," + cy + " " + x + "," + (cy - half) + " " + (x + half) + "," + cy + " " + x + "," + (cy + half);
}

function fillFor(kind: VariantRecord["kind"]): string {
  switch (kind) {
    case "snv":
    case "mnv":
      return "var(--primary, oklch(0.46 0.13 152))";
    case "ins":
      return "var(--chart-2, oklch(0.66 0.12 150))";
    case "del":
      return "var(--destructive, oklch(0.58 0.22 27))";
    case "sv":
      return "var(--impact-moderate, oklch(0.72 0.16 65))";
    default:
      return "var(--muted-foreground, oklch(0.48 0.028 152))";
  }
}
</script>

<style scoped>
.variant-track {
  position: relative;
  width: 100%;
}
.variant-track__svg {
  display: block;
  max-width: 100%;
}
.variant-track__state {
  margin: 0;
  padding: 1rem;
  text-align: center;
  font-size: var(--text-small, 0.875rem);
  line-height: var(--text-small--line-height, 1.55);
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
.variant-track__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin: 0.25rem 0 0;
  padding: 0;
  list-style: none;
  font-size: var(--text-caption, 0.75rem);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
.variant-track__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.variant-track__swatch {
  inline-size: 0.625rem;
  block-size: 0.625rem;
  border-radius: 0.25rem;
}
</style>
