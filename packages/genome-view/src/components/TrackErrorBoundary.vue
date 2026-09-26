<template>
  <div class="track-error-boundary">
    <div v-if="error" class="track-error-boundary__error" role="alert">
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
import { onErrorCaptured, ref } from "vue";

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

onErrorCaptured((caught) => {
  error.value = caught instanceof Error ? caught : new Error(String(caught));
  return false;
});

function retry(): void {
  error.value = null;
  emit("retry");
}
</script>
