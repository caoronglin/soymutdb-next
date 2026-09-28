<script setup lang="ts">
/**
 * Filter card: the bordered surface above a result set that holds the filter
 * controls and the apply/clear actions.
 *
 * Rendered as a real `<form>` so Enter submits (and a submit button keeps
 * working) exactly like the React baseline's inline AntD `Form`; the caller
 * owns all filter state and only listens to `submit`.
 */
defineEmits<{ submit: [] }>();
</script>

<template>
  <form
    class="mt-8 rounded-xl border bg-card p-4 shadow-sm md:p-5"
    role="search"
    @submit.prevent="$emit('submit')"
  >
    <div class="flex flex-wrap items-end gap-x-4 gap-y-4">
      <slot />
    </div>
    <div
      v-if="$slots.actions"
      class="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4"
    >
      <slot name="actions" />
    </div>
  </form>
</template>
