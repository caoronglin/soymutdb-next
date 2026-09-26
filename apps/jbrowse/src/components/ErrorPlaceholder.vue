<template>
  <div
    class="flex h-full w-full flex-col items-center justify-center gap-4 bg-muted/20 p-8 text-center"
    role="alert"
  >
    <div class="flex size-12 items-center justify-center rounded-full bg-destructive/10">
      <svg
        class="size-6 text-destructive"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
        <path d="M12 9v4" />
        <path d="M12 17h.01" />
      </svg>
    </div>
    <div>
      <h2 class="font-serif text-lg font-semibold">Unable to load genome browser</h2>
      <p class="mt-1 max-w-md text-sm text-muted-foreground">{{ message }}</p>
    </div>
    <button
      type="button"
      class="inline-flex h-7 items-center justify-center rounded-md border border-input bg-background px-3 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground"
      @click="emit('retry')"
    >
      Retry
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{ message: string }>();

const emit = defineEmits<{
  (event: "retry"): void;
}>();
</script>
