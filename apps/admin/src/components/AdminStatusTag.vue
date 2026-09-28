<template>
  <Tag :color="tone" :data-testid="testid">{{ label ?? status }}</Tag>
</template>

<script setup lang="ts">
import { computed } from "vue";

import { Tag } from "@soymutdb/ui-vue";

/**
 * Status pill with one tone vocabulary for the whole console.
 *
 * The status *text* defaults to exactly what the server returned — the tone is
 * presentation only — so a new backend status still renders (as neutral) instead
 * of being coerced into a known label. `label` overrides the text when the wire
 * value is a machine token that needs localising.
 */
const props = defineProps<{ status: string; label?: string; testid?: string }>();

const TONES: Record<string, string> = {
  published: "green",
  active: "green",
  completed: "green",
  healthy: "green",
  enabled: "green",
  ready: "green",
  default: "green",
  created: "green",
  running: "blue",
  processing: "blue",
  ingesting: "blue",
  validating: "blue",
  uploading: "blue",
  queued: "gold",
  pending: "gold",
  draft: "gold",
  skipped: "gold",
  unconfigured: "gold",
  archived: "default",
  cancelled: "default",
  disabled: "default",
  invalid: "red",
  failed: "red",
  error: "red",
  unhealthy: "red",
};

const tone = computed(() => TONES[props.status.toLowerCase()] ?? "default");
</script>

