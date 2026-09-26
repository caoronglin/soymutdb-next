<template>
  <div class="track-ruler" :aria-hidden="true">
    <span
      v-for="tick in ticks"
      :key="tick.bp"
      class="track-ruler__tick"
      :style="{ left: tick.x + 'px' }"
    >
      <span class="track-ruler__label">{{ tick.label }}</span>
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

import { computeTicks, type RulerRegion } from "../ruler";

const props = withDefaults(
  defineProps<{
    region: RulerRegion;
    widthPx?: number;
    targetPx?: number;
  }>(),
  { widthPx: 800, targetPx: 80 },
);

const ticks = computed(() => computeTicks(props.region, props.widthPx, props.targetPx));
</script>

<style scoped>
.track-ruler {
  position: relative;
  height: var(--ruler-height, 1.75rem);
  width: 100%;
}
.track-ruler__tick {
  position: absolute;
  top: 0;
  height: 100%;
  transform: translateX(-50%);
  border-left: 1px solid var(--border, oklch(0.905 0.02 148));
}
.track-ruler__label {
  position: absolute;
  top: 0;
  left: 0.25rem;
  white-space: nowrap;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: var(--text-caption, 0.75rem);
  line-height: var(--ruler-height, 1.75rem);
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
</style>
