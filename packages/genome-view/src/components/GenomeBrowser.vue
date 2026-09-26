<template>
  <div class="genome-browser" :data-assembly-key="props.assemblyKey" :data-ref-name="props.refName">
    <div class="genome-browser__ruler" data-testid="genome-ruler">
      <span class="genome-browser__ruler-label">{{ props.refName }}</span>
    </div>
    <div class="genome-browser__tracks" data-testid="genome-tracks">
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
        />
      </TrackErrorBoundary>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { TrackConfig } from "@soymutdb/genome-data";
import { resolveTrackRenderer, type TrackRendererDescriptor } from "../registry";
import TrackErrorBoundary from "./TrackErrorBoundary.vue";

const props = defineProps<{
  assemblyKey: string;
  refName: string;
  tracks: TrackConfig[];
}>();

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
