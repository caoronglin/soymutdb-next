<template>
  <div class="alignments-track" :data-track-id="props.track.trackId">
    <p v-if="props.loading" class="alignments-track__state" role="status">Loading alignments...</p>
    <p v-else-if="blocks.length === 0" class="alignments-track__state">No alignments in view</p>
    <svg
      v-else
      class="alignments-track__svg"
      :width="props.widthPx"
      :height="props.heightPx"
      :viewBox="viewBox"
      role="img"
      :aria-label="ariaLabel"
    >
      <g class="alignments-track__coverage" aria-hidden="true">
        <rect
          v-for="bar in coverageBars"
          :key="'cov-' + bar.bin"
          class="alignments-track__coverage-bar"
          :x="bar.x"
          :y="bar.y"
          :width="bar.w"
          :height="bar.h"
        />
      </g>
      <rect
        v-for="block in blocks"
        :key="block.id"
        class="alignments-track__read"
        :data-alignment-id="block.id"
        :x="block.x"
        :y="block.y"
        :width="block.w"
        :height="block.h"
        :fill="block.fill"
      >
        <title>{{ block.title }}</title>
      </rect>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { AlignmentRecord, TrackConfig } from "@soymutdb/genome-data";

import { clipToRegion, layoutIntervals, type RegionLike } from "../track-layout";

const props = withDefaults(
  defineProps<{
    track: TrackConfig;
    assemblyKey: string;
    refName: string;
    records?: AlignmentRecord[];
    region?: RegionLike;
    widthPx?: number;
    heightPx?: number;
    loading?: boolean;
  }>(),
  { records: () => [], widthPx: 800, heightPx: 140, loading: false },
);

const BIN_WIDTH_PX = 4;
const COVERAGE_FRACTION = 0.28;
const MAX_READ_ROW_HEIGHT = 14;

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

const coverageHeight = computed(() => Math.max(10, Math.round(props.heightPx * COVERAGE_FRACTION)));
const readsTop = computed(() => coverageHeight.value + 4);
const readsHeight = computed(() => Math.max(0, props.heightPx - readsTop.value));

const binCount = computed(() => Math.max(1, Math.min(256, Math.ceil(props.widthPx / BIN_WIDTH_PX))));

const coverageBars = computed(() => {
  const bins: number[] = Array.from({ length: binCount.value }, () => 0);
  const span = region.value.end - region.value.start;
  if (span > 0) {
    for (const record of props.records) {
      const clipped = clipToRegion({ start: record.start, end: record.end }, region.value);
      if (!clipped) continue;
      const first = Math.max(
        0,
        Math.floor(((clipped.start - region.value.start) / span) * bins.length),
      );
      const last = Math.min(
        bins.length - 1,
        Math.ceil(((clipped.end - region.value.start) / span) * bins.length) - 1,
      );
      for (let bin = first; bin <= last; bin += 1) bins[bin] += 1;
    }
  }
  const max = Math.max(1, ...bins);
  const step = props.widthPx / bins.length;
  return bins
    .map((count, bin) => {
      const h = (count / max) * coverageHeight.value;
      return { bin, x: bin * step, y: coverageHeight.value - h, w: Math.max(1, step), h };
    })
    .filter((bar) => bar.h > 0);
});

const readRowHeight = computed(() => {
  const rows = layout.value.rowCount;
  if (rows <= 0) return 0;
  return Math.max(2, Math.min(MAX_READ_ROW_HEIGHT, readsHeight.value / rows));
});

interface ReadBlock {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  fill: string;
  title: string;
}

const blocks = computed<ReadBlock[]>(() => {
  const rowHeight = readRowHeight.value;
  const result: ReadBlock[] = [];
  for (const placed of layout.value.placed) {
    const record = byId.value.get(placed.id);
    if (!record) continue;
    result.push({
      id: record.id,
      x: placed.x,
      y: readsTop.value + placed.row * rowHeight,
      w: placed.w,
      h: Math.max(1, rowHeight - 1),
      fill: fillFor(record.strand),
      title: titleOf(record),
    });
  }
  return result;
});

const viewBox = computed(() => "0 0 " + props.widthPx + " " + props.heightPx);
const ariaLabel = computed(
  () => props.track.name + " (" + blocks.value.length + " alignments on " + props.refName + ")",
);

function fillFor(strand: AlignmentRecord["strand"]): string {
  return strand === "-"
    ? "var(--chart-2, oklch(0.66 0.12 150))"
    : "var(--primary, oklch(0.46 0.13 152))";
}

function titleOf(record: AlignmentRecord): string {
  const coords = props.refName + ":" + (record.start + 1) + "-" + record.end;
  const mapq = record.mapq === undefined ? "MAPQ ?" : "MAPQ " + record.mapq;
  return record.readName + " " + coords + " " + mapq + " " + (record.cigar ?? "*");
}
</script>

<style scoped>
.alignments-track {
  position: relative;
  width: 100%;
}
.alignments-track__svg {
  display: block;
  max-width: 100%;
}
.alignments-track__coverage-bar {
  fill: var(--chart-3, oklch(0.72 0.11 210));
  opacity: 0.7;
}
.alignments-track__read {
  opacity: 0.9;
}
.alignments-track__read:hover {
  opacity: 1;
}
.alignments-track__state {
  margin: 0;
  padding: 1rem;
  text-align: center;
  font-size: var(--text-small, 0.875rem);
  line-height: var(--text-small--line-height, 1.55);
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
</style>
