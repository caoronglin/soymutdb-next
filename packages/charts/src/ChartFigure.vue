<script setup lang="ts">
import { Chart } from "@tanstack/vue-charts";
import { computed } from "vue";

import type { ChartDefinition } from "./definitions";
import { CHART_HEIGHT } from "./definitions";

/**
 * One chart plus its exact-value alternative.
 *
 * Every chart in the portal is wrapped in this component. It renders the graphic
 * and a `<details>` holding a table of the same numbers, so no value exists only
 * inside an SVG — the accessible alternative is part of the component, not
 * something each page remembers to add.
 */
const props = withDefaults(
  defineProps<{
    /** A definition built by the helpers in `./definitions`. */
    definition: ChartDefinition;
    data: readonly unknown[];
    /** Accessible name for the graphic. */
    label: string;
    /** Longer description of what the chart shows. */
    description?: string;
    /** Column headers for the value table. */
    tableColumns: readonly string[];
    /** Row extractor for the value table: returns the cell strings. */
    tableRow: (datum: never) => readonly string[];
    emptyText?: string;
    height?: number;
  }>(),
  {
    description: undefined,
    emptyText: "No data for this selection.",
    height: CHART_HEIGHT,
  },
);

const hasData = computed(() => props.data.length > 0);
</script>

<template>
  <figure class="m-0">
    <div
      v-if="hasData"
      role="img"
      :aria-label="label"
      :aria-describedby="description ? 'chart-description' : undefined"
    >
      <p v-if="description" id="chart-description" class="sr-only">{{ description }}</p>
      <Chart :definition="definition" :data="data" :height="height" />
    </div>
    <p
      v-else
      class="rounded-md border border-dashed p-6 text-center text-sm opacity-70"
      data-testid="chart-empty"
    >
      {{ emptyText }}
    </p>

    <figcaption class="mt-2 text-xs opacity-70">
      <details v-if="hasData">
        <summary class="cursor-pointer">Show the values as a table</summary>
        <table class="mt-2 w-full text-sm" data-testid="chart-values">
          <thead class="text-left opacity-60">
            <tr>
              <th v-for="column in tableColumns" :key="column" scope="col" class="py-1">
                {{ column }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(datum, index) in data" :key="index" class="border-t">
              <td v-for="(cell, cellIndex) in tableRow(datum as never)" :key="cellIndex" class="py-1">
                {{ cell }}
              </td>
            </tr>
          </tbody>
        </table>
      </details>
    </figcaption>
  </figure>
</template>
