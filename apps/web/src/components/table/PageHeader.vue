<script setup lang="ts">
/**
 * Page title band: optional eyebrow, h1, optional description, and a right-hand
 * action area. Mirrors the React baseline's `eyebrow` + `font-display` heading
 * + muted lede + trailing action button, which every list/detail route opened
 * with.
 *
 * The title can be overridden through the `title` slot when the heading needs
 * inline markup (a monospace accession, a badge); `badges` renders between the
 * eyebrow and the heading.
 */
withDefaults(
  defineProps<{
    eyebrow?: string;
    title?: string;
    description?: string;
  }>(),
  { eyebrow: "", title: "", description: "" },
);
</script>

<template>
  <header class="flex flex-wrap items-start justify-between gap-4">
    <div class="min-w-0">
      <p v-if="eyebrow" class="eyebrow">{{ eyebrow }}</p>
      <div v-if="$slots.badges" class="mt-2 flex flex-wrap items-center gap-2">
        <slot name="badges" />
      </div>
      <h1 class="mt-2 font-display text-3xl font-semibold tracking-tight md:text-4xl">
        <slot name="title">{{ title }}</slot>
      </h1>
      <p v-if="description" class="mt-3 max-w-2xl text-muted-foreground">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="flex shrink-0 flex-wrap items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
