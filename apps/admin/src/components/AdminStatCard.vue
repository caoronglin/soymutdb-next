<template>
  <article class="admin-stat" data-testid="stat-card">
    <div class="admin-stat-top">
      <p class="admin-stat-label">{{ label }}</p>
      <span v-if="$slots.icon" class="admin-stat-icon" aria-hidden="true">
        <slot name="icon" />
      </span>
    </div>
    <p class="admin-stat-value" :data-testid="testid">{{ value }}</p>
    <p v-if="trend" class="admin-stat-trend" :data-positive="trend.positive">
      {{ trend.value }}
    </p>
  </article>
</template>

<script setup lang="ts">
/**
 * Metric tile for the dashboard.
 *
 * `value` is a string so the caller decides what a missing number looks like
 * ("…" while pending, "—" on error) instead of the tile inventing a zero.
 */
defineProps<{
  label: string;
  value: string;
  trend?: { value: string; positive: boolean } | null;
  testid?: string;
}>();
</script>
