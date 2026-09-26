<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { capabilitiesApi } from "@soymutdb/api-client";
import { ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Capability flags.
 *
 * This page exists to answer one question honestly: which import/scientific
 * capabilities are actually enabled in this deployment. Every flag is shown with
 * the state the backend reports, including the ones that are off — a page that
 * lists only the enabled features makes an unimplemented one indistinguishable
 * from a missing one.
 */
const queryClient = useQueryClient();
const errorMessage = ref("");

const query = useQuery({
  queryKey: ["admin", "features"],
  queryFn: () => capabilitiesApi.adminGet(),
  staleTime: 60_000,
});

const features = computed(() => toValue(query.data)?.features ?? []);

const toggleMutation = useMutation({
  mutationFn: (payload: Record<string, boolean>) => capabilitiesApi.adminUpdate(payload),
  onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin", "features"] }),
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

function toggle(key: string, enabled: boolean) {
  toggleMutation.mutate({ [key]: enabled });
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div>
      <h1 class="text-xl font-semibold">{{ t("admin.features") }}</h1>
      <p class="mt-1 max-w-3xl text-sm opacity-70">
        {{ t("admin.featuresHint") }}
      </p>

      <p v-if="query.isPending.value" class="mt-4 text-sm opacity-70">{{ t("common.loading") }}</p>
      <p v-else-if="query.isError.value" data-testid="features-error" class="mt-4 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <p v-else-if="features.length === 0" data-testid="features-empty" class="mt-4 text-sm opacity-70">
        {{ t("common.noData") }}
      </p>
      <table v-else class="mt-4 w-full text-sm" data-testid="features-table">
        <thead class="text-left opacity-60">
          <tr>
            <th scope="col" class="py-2">{{ t("admin.featureCapability") }}</th>
            <th scope="col" class="py-2">{{ t("common.status") }}</th>
            <th scope="col" class="py-2">{{ t("admin.featureDescription") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="feature in features" :key="feature.key" class="border-t" data-testid="feature-row">
            <td class="py-2 font-mono text-xs">{{ feature.key }}</td>
            <td class="py-2">
              <button
                type="button"
                :data-testid="'feature-toggle-' + feature.key"
                :aria-pressed="feature.enabled"
                @click="toggle(feature.key, !feature.enabled)"
              >
                <Tag :color="feature.enabled ? 'green' : 'default'" data-testid="feature-state">
                  {{ feature.enabled ? "ON" : "OFF" }}
                </Tag>
              </button>
            </td>
            <td class="py-2 text-xs opacity-70">{{ feature.description ?? "—" }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="errorMessage" role="alert" class="mt-3 text-sm text-red-700" data-testid="features-error-save">
        {{ errorMessage }}
      </p>
    </div>
  </ConfigProvider>
</template>
