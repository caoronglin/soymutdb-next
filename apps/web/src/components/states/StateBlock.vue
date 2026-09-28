<script setup lang="ts">
import AppIcon from "../table/AppIcon.vue";
import type { IconName } from "../table/table-types";

/**
 * Empty / error / loading placeholder with the same visual weight as the
 * React baseline's AntD `Empty` + `Alert` combination: a muted icon medallion,
 * a short title, an optional explanation and a slot for the recovery action.
 *
 * Attributes fall through to the root element, so a caller can pin its own
 * `data-testid` without an extra wrapper.
 */
withDefaults(
  defineProps<{
    variant?: "empty" | "error" | "loading";
    title: string;
    description?: string;
    icon?: IconName;
    /** Horizontal padding/skeleton row count for the loading variant. */
    rows?: number;
  }>(),
  { variant: "empty", icon: "inbox", description: "", rows: 4 },
);
</script>

<template>
  <div
    class="flex flex-col items-center gap-3 rounded-xl border bg-card px-6 py-10 text-center shadow-sm"
    :role="variant === 'error' ? 'alert' : 'status'"
  >
    <div
      v-if="variant !== 'loading'"
      class="flex size-10 items-center justify-center rounded-full"
      :class="variant === 'error' ? 'bg-destructive/10 text-destructive' : 'bg-muted text-muted-foreground'"
    >
      <AppIcon :name="variant === 'error' ? 'alert' : icon" class="size-5" />
    </div>
    <template v-if="variant === 'loading'">
      <div class="grid w-full max-w-md gap-2">
        <div
          v-for="index in rows"
          :key="index"
          class="h-4 w-full animate-pulse rounded bg-muted"
        />
      </div>
      <p class="sr-only">{{ title }}</p>
    </template>
    <template v-else>
      <p class="font-medium">{{ title }}</p>
      <p v-if="description" class="max-w-md text-sm text-muted-foreground">{{ description }}</p>
      <div v-if="$slots.action" class="mt-1 flex flex-wrap items-center justify-center gap-2">
        <slot name="action" />
      </div>
    </template>
  </div>
</template>
