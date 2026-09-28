<script setup lang="ts">
import { onErrorCaptured, ref } from "vue";

import { Button } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Portal-wide render error boundary.
 *
 * Vue has no `componentDidCatch`: `onErrorCaptured` is the equivalent hook, and
 * without one a thrown render error unmounts the whole tree and leaves a blank
 * page (the React portal wrapped its router in `ErrorBoundary`). The default
 * slot is re-keyed by `attempt`, so "Retry" remounts the failed subtree instead
 * of reloading the document.
 */
const error = ref<Error | null>(null);
const attempt = ref(0);

onErrorCaptured((caught) => {
  error.value = caught instanceof Error ? caught : new Error(String(caught));
  console.error("[AppErrorBoundary]", caught);
  // Stop propagation: this component renders the fallback for the subtree.
  return false;
});

function retry() {
  error.value = null;
  attempt.value += 1;
}
</script>

<template>
  <div
    v-if="error"
    role="alert"
    class="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 px-6 text-center"
    data-testid="app-error-boundary"
  >
    <h1 class="text-xl font-semibold">{{ t("common.error") }}</h1>
    <p class="text-sm text-muted-foreground">{{ t("common.errorDescription") }}</p>
    <p v-if="error.message" class="break-all text-xs text-muted-foreground/80">{{ error.message }}</p>
    <Button type="primary" class="mt-2" data-testid="app-error-retry" @click="retry">
      {{ t("common.retry") }}
    </Button>
  </div>
  <slot v-else :attempt="attempt" />
</template>
