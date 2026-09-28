<template>
  <div class="admin-page">
    <AdminPageHeader :title="t('admin.features')" :description="t('admin.featuresHint')" />

    <p v-if="errorMessage" role="alert" class="admin-state admin-state--error" data-testid="features-error-save">
      {{ errorMessage }}
    </p>

    <AdminState v-if="query.isPending.value" state="loading" testid="features-loading" />
    <AdminState
      v-else-if="query.isError.value"
      state="error"
      testid="features-error"
      :title="t('common.errorDescription')"
    >
      <template #actions>
        <Button size="small" data-testid="features-retry" @click="query.refetch()">
          {{ t("common.retry") }}
        </Button>
      </template>
    </AdminState>
    <AdminState
      v-else-if="features.length === 0"
      state="empty"
      testid="features-empty"
      :title="t('common.noData')"
    />

    <AdminCard v-else>
      <div class="admin-table-wrap">
        <table class="admin-table" data-testid="features-table">
          <thead>
            <tr>
              <th scope="col">{{ t("admin.featureCapability") }}</th>
              <th scope="col">{{ t("common.status") }}</th>
              <th scope="col">{{ t("admin.featureDescription") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="feature in features" :key="feature.key" data-testid="feature-row">
              <td class="font-mono text-xs">{{ feature.key }}</td>
              <td>
                <button
                  type="button"
                  class="cursor-pointer disabled:cursor-progress"
                  :disabled="toggleMutation.isPending.value"
                  :data-testid="'feature-toggle-' + feature.key"
                  :aria-pressed="feature.enabled"
                  @click="toggle(feature.key, !feature.enabled)"
                >
                  <AdminStatusTag
                    :status="feature.enabled ? 'enabled' : 'disabled'"
                    testid="feature-state"
                  />
                </button>
              </td>
              <td class="text-xs text-muted-foreground">{{ feature.description ?? "—" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </AdminCard>
  </div>
</template>

<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { capabilitiesApi } from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
import { t } from "../lib/i18n";

/**
 * Capability flags.
 *
 * This page exists to answer one question honestly: which import/scientific
 * capabilities are actually enabled in this deployment. Every flag is shown with
 * the state the backend reports, including the ones that are off — a page that
 * lists only the enabled features makes an unimplemented one indistinguishable
 * from a missing one.
 *
 * The pill keeps the wire value ("ON"/"OFF" is the old rendering) but the tone
 * now comes from the shared status vocabulary. The toggle is disabled while the
 * mutation is in flight so a double click cannot race itself.
 */
const queryClient = useQueryClient();
const errorMessage = ref("");

const query = useQuery({
  queryKey: ["admin", "features"],
  queryFn: () => capabilitiesApi.adminGet(),
});

const features = computed(() => toValue(query.data)?.features ?? []);

const toggleMutation = useMutation({
  mutationFn: (payload: Record<string, boolean>) => capabilitiesApi.adminUpdate(payload),
  onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin", "features"] }),
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

function toggle(key: string, enabled: boolean): void {
  toggleMutation.mutate({ [key]: enabled });
}
</script>
