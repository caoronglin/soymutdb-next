<template>
  <fieldset class="track-selector">
    <legend class="track-selector__legend">{{ props.legend }}</legend>
    <p v-if="props.tracks.length === 0" class="track-selector__empty">{{ props.emptyLabel }}</p>
    <label v-for="track in props.tracks" :key="track.trackId" class="track-selector__item">
      <input
        class="track-selector__checkbox"
        type="checkbox"
        :value="track.trackId"
        :checked="selected.includes(track.trackId)"
        @change="onToggle(track.trackId, $event)"
      />
      <span class="track-selector__name">{{ track.name }}</span>
    </label>
  </fieldset>
</template>

<script setup lang="ts">
import type { TrackConfig } from "@soymutdb/genome-data";

const props = withDefaults(
  defineProps<{
    tracks: TrackConfig[];
    legend?: string;
    emptyLabel?: string;
  }>(),
  { legend: "Tracks", emptyLabel: "No tracks available" },
);

const selected = defineModel<string[]>({ default: () => [] });

function onToggle(trackId: string, event: Event): void {
  const checked = (event.target as HTMLInputElement).checked;
  selected.value = checked
    ? [...selected.value, trackId]
    : selected.value.filter((id) => id !== trackId);
}
</script>

<style scoped>
.track-selector {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin: 0;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border, oklch(0.905 0.02 148));
  border-radius: var(--radius-md, 0.625rem);
  background: var(--card, #fff);
}
.track-selector__legend {
  padding-inline: 0.25rem;
  font-size: var(--text-caption, 0.75rem);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
.track-selector__item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: var(--track-height, 1.5rem);
  cursor: pointer;
}
.track-selector__checkbox {
  inline-size: 1rem;
  block-size: 1rem;
  accent-color: var(--primary, oklch(0.46 0.13 152));
}
.track-selector__checkbox:focus-visible {
  outline: 2px solid var(--ring, oklch(0.55 0.14 152));
  outline-offset: 2px;
}
.track-selector__name {
  font-size: var(--text-small, 0.875rem);
  color: var(--foreground, oklch(0.195 0.028 152));
}
.track-selector__empty {
  margin: 0;
  font-size: var(--text-small, 0.875rem);
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
</style>
