<template>
  <figure class="admin-card">
    <figcaption class="admin-card-head">
      <div class="min-w-0">
        <h3 class="admin-section-title">{{ title }}</h3>
        <p v-if="description" class="admin-section-desc">{{ description }}</p>
      </div>
      <ul v-if="series.length" class="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <li v-for="item in series" :key="item.name" class="flex items-center gap-1.5">
          <span aria-hidden="true" class="size-2 rounded-full" :style="{ background: item.color }" />
          {{ item.name }}
        </li>
      </ul>
    </figcaption>

    <div class="admin-card-body">
      <svg
        v-if="labels.length && series.length"
        viewBox="0 0 300 100"
        preserveAspectRatio="none"
        class="h-40 w-full"
        role="img"
        :aria-label="title"
      >
        <line
          v-for="line in GRID"
          :key="line"
          x1="0"
          :x2="300"
          :y1="line"
          :y2="line"
          stroke="var(--border)"
          stroke-width="0.4"
          vector-effect="non-scaling-stroke"
        />

        <template v-if="variant === 'bar'">
          <rect
            v-for="bar in bars"
            :key="bar.key"
            :x="bar.x"
            :y="bar.y"
            :width="bar.width"
            :height="bar.height"
            :fill="bar.color"
            rx="0.6"
          />
        </template>

        <polyline
          v-for="item in series"
          v-else
          :key="item.name"
          :points="polyline(item.values)"
          fill="none"
          :stroke="item.color"
          stroke-width="1.2"
          stroke-linejoin="round"
          stroke-linecap="round"
          vector-effect="non-scaling-stroke"
        />
      </svg>

      <p v-else class="text-xs text-muted-foreground">{{ t("common.noData") }}</p>

      <div v-if="labels.length" class="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span class="font-mono">{{ labels[0] }}</span>
        <span class="font-mono">{{ labels[labels.length - 1] }}</span>
      </div>
    </div>
  </figure>
</template>

<script setup lang="ts">
import { computed } from "vue";

import { t } from "../lib/i18n";

/**
 * Dependency-free chart for the dashboard series.
 *
 * The React admin used ECharts; the Vue port carried no chart library and the
 * dashboard had lost all three charts. A single scaled SVG covers the shapes
 * these series need (two-to-three comparable lines, or grouped bars), so no
 * dependency is added.
 */
interface ChartSeries {
  name: string;
  color: string;
  values: number[];
}

const props = withDefaults(
  defineProps<{
    title: string;
    description?: string;
    labels: string[];
    series: ChartSeries[];
    variant?: "line" | "bar";
  }>(),
  { description: "", variant: "line" },
);

const GRID = [0, 25, 50, 75, 100];
const HEIGHT = 100;
const WIDTH = 300;

const max = computed(() =>
  Math.max(1, ...props.series.flatMap((item) => item.values.map((value) => value || 0))),
);

/** Scale one series to the shared 0..100 y-axis (top-origin, so it is inverted). */
function polyline(values: number[]): string {
  const step = values.length > 1 ? WIDTH / (values.length - 1) : 0;
  return values
    .map((value, index) => `${(index * step).toFixed(2)},${(HEIGHT - ((value || 0) / max.value) * HEIGHT).toFixed(2)}`)
    .join(" ");
}

const bars = computed(() => {
  const count = props.labels.length;
  if (count === 0) return [];
  const groupWidth = WIDTH / count;
  const barWidth = Math.max(groupWidth / (props.series.length + 1), 0.4);
  return props.series.flatMap((item, seriesIndex) =>
    item.values.map((value, index) => {
      const height = ((value || 0) / max.value) * HEIGHT;
      return {
        key: `${item.name}-${index}`,
        x: index * groupWidth + seriesIndex * barWidth,
        y: HEIGHT - height,
        width: barWidth,
        height,
        color: item.color,
      };
    }),
  );
});
</script>
