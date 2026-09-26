<template>
  <div class="track-error-boundary">
    <div
      v-if="error"
      ref="alertRef"
      class="track-error-boundary__error"
      role="alert"
      aria-live="assertive"
      tabindex="-1"
    >
      <p class="track-error-boundary__title">{{ props.title }}</p>
      <p class="track-error-boundary__message">{{ error.message }}</p>
      <button class="track-error-boundary__retry" type="button" @click="retry">
        {{ props.retryLabel }}
      </button>
    </div>
    <slot v-else />
  </div>
</template>

<script setup lang="ts">
import { nextTick, onErrorCaptured, ref } from "vue";

const props = withDefaults(
  defineProps<{
    title?: string;
    retryLabel?: string;
  }>(),
  {
    title: "Track failed to render",
    retryLabel: "Retry",
  },
);

const emit = defineEmits<{
  (event: "retry"): void;
}>();

const error = ref<Error | null>(null);
const alertRef = ref<HTMLElement | null>(null);

onErrorCaptured((caught) => {
  error.value = caught instanceof Error ? caught : new Error(String(caught));
  // Move focus to the inline alert so keyboard users land on the recovery
  // action instead of silently losing focus with the failed track.
  void nextTick(() => alertRef.value?.focus());
  return false;
});

function retry(): void {
  error.value = null;
  emit("retry");
}
</script>

<style scoped>
.track-error-boundary {
  display: block;
}
.track-error-boundary__error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.375rem;
  padding: 0.75rem;
  border: 1px solid var(--destructive, oklch(0.58 0.22 27));
  border-radius: var(--radius-md, 0.625rem);
  background: color-mix(in oklch, var(--destructive, oklch(0.58 0.22 27)) 8%, transparent);
}
.track-error-boundary__error:focus-visible {
  outline: 2px solid var(--ring, oklch(0.55 0.14 152));
  outline-offset: 2px;
}
.track-error-boundary__title {
  margin: 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--foreground, oklch(0.195 0.028 152));
}
.track-error-boundary__message {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
.track-error-boundary__retry {
  min-height: 32px;
  padding-inline: 0.75rem;
  border: 1px solid var(--border, oklch(0.905 0.02 148));
  border-radius: var(--radius-md, 0.625rem);
  background: var(--card, #fff);
  color: var(--foreground, oklch(0.195 0.028 152));
  font-weight: 600;
  cursor: pointer;
}
.track-error-boundary__retry:focus-visible {
  outline: 2px solid var(--ring, oklch(0.55 0.14 152));
  outline-offset: 2px;
}
</style>
