<script setup lang="ts">
import { computed } from "vue";

import { t } from "../lib/i18n";
import { useInstanceContext } from "../lib/instance-context";

/**
 * P1-07: every write form states its target.
 *
 * Selecting a remote instance only changes the displayed context (probe /
 * portal link); writes always go to the local deployment. This note makes that
 * explicit next to the form instead of leaving the remote badge to imply the
 * write target.
 */
const { currentInstance, localInstance, isRemote } = useInstanceContext();

function hostOf(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new URL(value).host;
  } catch {
    return value;
  }
}

const localLabel = computed(() => {
  const instance = localInstance.value;
  return instance ? `${instance.name} (${instance.code})` : "—";
});
const remoteLabel = computed(() => {
  const instance = currentInstance.value;
  return instance ? `${instance.name} (${instance.code})` : "—";
});
const localHost = computed(() => hostOf(localInstance.value?.api_base_url));
</script>

<template>
  <p
    v-if="isRemote"
    role="note"
    data-testid="write-target-remote"
    class="mt-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800"
  >
    {{ t("admin.instances.writeTargetRemote", { instance: remoteLabel, local: localLabel }) }}
  </p>
  <p v-else data-testid="write-target-local" class="mt-3 text-xs opacity-70">
    {{ t("admin.instances.writeTargetLocal", { instance: localLabel, server: localHost }) }}
  </p>
</template>
