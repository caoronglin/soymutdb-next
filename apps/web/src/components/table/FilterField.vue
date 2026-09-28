<script setup lang="ts">
/**
 * One labelled filter control inside `FilterCard`. Keeps the label markup,
 * spacing and `<label>`/`for` association identical across the list pages so a
 * screen reader reaches every control.
 */
withDefaults(defineProps<{ label: string; forId?: string }>(), { forId: undefined });
</script>

<template>
  <label :for="forId" class="min-w-0 text-sm">
    <span class="mb-1 block font-medium text-foreground">{{ label }}</span>
    <slot />
  </label>
</template>
