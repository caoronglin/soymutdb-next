<template>
  <div class="genome-browser" :data-assembly-key="props.assemblyKey" :data-ref-name="props.refName">
    <div class="genome-browser__ruler" data-testid="genome-ruler">
      <span class="genome-browser__ruler-label">{{ props.refName }}</span>
      <TrackRuler v-if="props.region" :region="props.region" :width-px="props.widthPx" />
    </div>
    <div class="genome-browser__tracks" data-testid="genome-tracks">
      <p v-if="resolvedTracks.length === 0" class="genome-browser__empty">
        {{ props.emptyLabel }}
      </p>
      <TrackErrorBoundary
        v-for="entry in resolvedTracks"
        :key="entry.track.trackId"
        class="genome-browser__track"
        :title="`Track ${entry.track.name} failed to render`"
      >
        <component
          :is="entry.descriptor.component"
          :track="entry.track"
          :assembly-key="props.assemblyKey"
          :ref-name="props.refName"
          :region="props.region"
          :width-px="props.widthPx"
          :provider="props.provider"
          :assemblies="props.assemblies"
        />
      </TrackErrorBoundary>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { AssemblyContext, FileProvider, TrackConfig } from "@soymutdb/genome-data";
import { resolveTrackRenderer, type TrackRendererDescriptor } from "../registry";
import type { RulerRegion } from "../ruler";
import TrackErrorBoundary from "./TrackErrorBoundary.vue";
import TrackRuler from "./TrackRuler.vue";

const props = withDefaults(
  defineProps<{
    assemblyKey: string;
    refName: string;
    tracks: TrackConfig[];
    /** Optional viewport window; when present the ruler draws ticks. */
    region?: RulerRegion;
    widthPx?: number;
    emptyLabel?: string;
    provider?: FileProvider;
    assemblies?: readonly AssemblyContext[];
  }>(),
  { widthPx: 800, emptyLabel: "No tracks available" },
);

interface ResolvedTrack {
  track: TrackConfig;
  descriptor: TrackRendererDescriptor;
}

/** Unknown types already logged, so each one warns at most once per mount. */
const warnedTypes = new Set<string>();

const resolvedTracks = computed<ResolvedTrack[]>(() => {
  const resolved: ResolvedTrack[] = [];
  for (const track of props.tracks) {
    const descriptor = resolveTrackRenderer(track.type);
    if (!descriptor) {
      if (!warnedTypes.has(track.type)) {
        warnedTypes.add(track.type);
        console.warn(
          `[GenomeBrowser] unknown track type "${track.type}" (track "${track.trackId}") skipped`,
        );
      }
      continue;
    }
    resolved.push({ track, descriptor });
  }
  return resolved;
});
</script>

<style scoped>
.genome-browser {
  display: flex;
  flex-direction: column;
  min-inline-size: 0;
  border: 1px solid var(--border, oklch(0.905 0.02 148));
  border-radius: var(--radius-lg, 0.875rem);
  background: var(--card, #fff);
  overflow: hidden;
}
.genome-browser__ruler {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-height: var(--ruler-height, 1.75rem);
  padding-inline: 0.75rem;
  border-block-end: 1px solid var(--border, oklch(0.905 0.02 148));
  background: color-mix(in oklch, var(--muted, oklch(0.968 0.012 148)) 30%, transparent);
  color: var(--muted-foreground, oklch(0.48 0.028 152));
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: var(--text-caption, 0.75rem);
}
.genome-browser__ruler-label {
  flex: none;
  font-weight: 600;
}
.genome-browser__tracks {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem;
  min-block-size: 6rem;
}
.genome-browser__empty {
  margin: 0;
  padding: 1.5rem;
  text-align: center;
  color: var(--muted-foreground, oklch(0.48 0.028 152));
  font-size: var(--text-small, 0.875rem);
}
.genome-browser__track {
  display: block;
  border: 1px solid var(--border, oklch(0.905 0.02 148));
  border-radius: var(--radius-md, 0.625rem);
  overflow: hidden;
}
</style>
