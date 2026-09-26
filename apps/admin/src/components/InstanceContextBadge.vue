<script setup lang="ts">
import { computed } from "vue";

import { Tag } from "@soymutdb/ui-vue";

import { useInstanceContext } from "../lib/instance-context";
import { t } from "../lib/i18n";

/**
 * Target identity shown on every console page.
 *
 * Constraint 5: any operation must display the target instance and the
 * environment. The badge names the instance, the release the console pins its
 * requests to, and the API host that will receive them, so a write is never
 * one scroll away from the context it applies to. Remote registrations are
 * marked registration-only: the console can display and probe them, not
 * administer them.
 */
const { currentInstance, isRemote, isLoading } = useInstanceContext();
const releaseId = import.meta.env.VITE_SOYMUTDB_RELEASE_ID ?? "active";

function hostOf(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new URL(value).host;
  } catch {
    return value;
  }
}

const instanceLabel = computed(() => {
  const instance = currentInstance.value;
  if (instance) return `${instance.name} (${instance.code})`;
  return isLoading.value ? t("common.loading") : "—";
});
const serverHost = computed(() => hostOf(currentInstance.value?.api_base_url));
</script>

<template>
  <RouterLink
    to="/instances"
    class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
    :aria-label="t('admin.instances.context')"
    data-testid="instance-context"
  >
    <span class="max-w-40 truncate font-medium" data-testid="instance-context-instance">
      {{ instanceLabel }}
    </span>
    <span aria-hidden="true" class="opacity-40">·</span>
    <span class="truncate" data-testid="instance-context-release">
      {{ t("admin.instances.releaseLabel") }} {{ releaseId }}
    </span>
    <span aria-hidden="true" class="opacity-40">·</span>
    <span class="truncate font-mono" data-testid="instance-context-server">
      {{ t("admin.instances.server") }} {{ serverHost }}
    </span>
    <Tag v-if="isRemote" color="gold" data-testid="instance-context-remote">
      {{ t("admin.instances.registrationOnly") }}
    </Tag>
  </RouterLink>
</template>
