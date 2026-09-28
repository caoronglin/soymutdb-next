<template>
  <header class="admin-page-header">
    <div class="admin-page-heading">
      <h1 class="admin-page-title" :data-testid="testid">
        {{ title }}
      </h1>
      <p v-if="description" class="admin-page-desc">{{ description }}</p>
      <slot name="meta" />
    </div>
    <div v-if="$slots.actions" class="admin-page-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup lang="ts">
/**
 * The one page header in the console: title, optional description, a meta slot
 * for context chips, and an actions slot for the page's primary operation.
 *
 * The React console repeated this block by hand on every route; the Vue port had
 * drifted to a bare `<h1>` on most of them, with the primary action (or the
 * description that explains what the page is for) missing entirely. Centralising
 * it is what makes "every page looks the same" true rather than aspirational.
 */
withDefaults(
  defineProps<{
    title: string;
    description?: string;
    /** `data-testid` for the `<h1>`, when a test or E2E anchor needs one. */
    testid?: string;
  }>(),
  { description: "", testid: undefined },
);
</script>
