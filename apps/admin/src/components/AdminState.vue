<template>
  <!-- Loading is a skeleton, not the word "Loading": the React console used
       pulse rows so the page does not reflow when data lands. -->
  <div
    v-if="state === 'loading'"
    class="grid gap-2"
    :data-testid="testid"
    aria-busy="true"
  >
    <div v-for="row in rows" :key="row" class="admin-skeleton shimmer" />
  </div>

  <div
    v-else
    class="admin-state"
    :class="state === 'error' ? 'admin-state--error' : 'admin-state--empty'"
    :role="state === 'error' ? 'alert' : undefined"
    :data-testid="testid"
  >
    <p v-if="title" class="admin-state-title">{{ title }}</p>
    <p v-if="description">{{ description }}</p>
    <slot />
    <div v-if="$slots.actions" class="admin-page-actions mt-1">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Explicit loading / error / empty presentation.
 *
 * The rule the console follows is that none of the three may be silent and none
 * may be faked: an error is never rendered as an empty list, and a page never
 * shows a zero that really means "the request failed".
 */
withDefaults(
  defineProps<{
    state: "loading" | "error" | "empty";
    title?: string;
    description?: string;
    /** Skeleton row count while `state` is `loading`. */
    rows?: number;
    testid?: string;
  }>(),
  { title: "", description: "", rows: 3, testid: undefined },
);
</script>
