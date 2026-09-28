<template>
  <section class="admin-card" :data-testid="testid">
    <header v-if="title || description || $slots.actions" class="admin-card-head">
      <div class="min-w-0">
        <h2 v-if="title" class="admin-section-title">{{ title }}</h2>
        <p v-if="description" class="admin-section-desc">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="admin-page-actions">
        <slot name="actions" />
      </div>
    </header>

    <div class="admin-card-body">
      <slot />
    </div>

    <footer v-if="$slots.footer" class="admin-card-foot">
      <slot name="footer" />
    </footer>
  </section>
</template>

<script setup lang="ts">
/**
 * Bordered content card — the second half of the console's page contract
 * (header → content card). A page that puts a table or a form straight onto the
 * background reads as unfinished next to one that does not.
 */
withDefaults(
  defineProps<{
    title?: string;
    description?: string;
    testid?: string;
  }>(),
  { title: "", description: "", testid: undefined },
);
</script>
