<template>
  <footer class="border-t border-border bg-card px-4 py-2 text-center text-xs text-muted-foreground">
    Powered by JBrowse 2 · SoyMutDB Genome Browser ·
    <span v-if="activeCount > 0">{{ activeCount.toLocaleString() }} tracks loaded</span>
  </footer>
</template>

<script setup lang="ts">
defineProps<{ activeCount: number }>();
</script>
