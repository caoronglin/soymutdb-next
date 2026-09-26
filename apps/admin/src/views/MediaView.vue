<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { archiveMediaAsset, listMediaAssets, type MediaAsset } from "@soymutdb/api-client";
import { formatDate, formatFileSize } from "@soymutdb/shared/format";
import { ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Media library.
 *
 * Assets are archived rather than deleted: an image is referenced by published
 * news and pages, so a hard delete would break those records. The list shows the
 * archive state so an operator can tell "removed from the picker" apart from
 * "gone".
 */
const queryClient = useQueryClient();
const page = ref(1);
const errorMessage = ref("");

const query = useQuery({
  queryKey: computed(() => ["admin", "media", page.value]),
  queryFn: () => listMediaAssets({ page: page.value, page_size: 24 }),
  staleTime: 30_000,
});

const items = computed<MediaAsset[]>(() => toValue(query.data)?.items ?? []);
const total = computed(() => toValue(query.data)?.total ?? 0);
const lastPage = computed(() => Math.max(1, Math.ceil(total.value / 24)));

const archiveMutation = useMutation({
  mutationFn: (id: string) => archiveMediaAsset(id),
  onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin", "media"] }),
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div>
      <h1 class="text-xl font-semibold">{{ t("admin.uploads") }}</h1>

      <p v-if="query.isPending.value" class="mt-4 text-sm opacity-70">{{ t("common.loading") }}</p>
      <p v-else-if="query.isError.value" data-testid="media-error" class="mt-4 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <p v-else-if="items.length === 0" data-testid="media-empty" class="mt-4 text-sm opacity-70">
        {{ t("common.noData") }}
      </p>
      <template v-else>
        <p class="mt-4 text-sm opacity-70">{{ t("common.total") }}: {{ total }}</p>
        <table class="mt-2 w-full text-sm" data-testid="media-table">
          <thead class="text-left opacity-60">
            <tr>
              <th scope="col" class="py-2">{{ t("common.file") }}</th>
              <th scope="col" class="py-2">{{ t("common.size") }}</th>
              <th scope="col" class="py-2">{{ t("common.status") }}</th>
              <th scope="col" class="py-2">{{ t("common.date") }}</th>
              <th scope="col" class="py-2">{{ t("common.actions") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="asset in items" :key="asset.id" class="border-t" data-testid="media-row">
              <td class="py-2 font-mono text-xs">{{ asset.original_filename }}</td>
              <td class="py-2 text-xs">{{ formatFileSize(asset.size_bytes ?? null) }}</td>
              <td class="py-2">
                <Tag :color="asset.status === 'archived' ? 'default' : 'green'" data-testid="media-status">
                  {{ asset.status ?? "active" }}
                </Tag>
              </td>
              <td class="py-2 text-xs opacity-70">{{ formatDate(asset.created_at) }}</td>
              <td class="py-2">
                <button
                  v-if="asset.status !== 'archived'"
                  type="button"
                  class="underline text-red-700"
                  :data-testid="'media-archive-' + asset.id"
                  @click="archiveMutation.mutate(asset.id)"
                >
                  {{ t("common.delete") }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="errorMessage" role="alert" class="mt-3 text-sm text-red-700">{{ errorMessage }}</p>
        <nav class="mt-4 flex items-center gap-3" :aria-label="t('common.pagination')">
          <button
            type="button"
            class="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            :disabled="page <= 1"
            @click="page -= 1"
          >
            {{ t("common.previous") }}
          </button>
          <span class="text-sm opacity-70">{{ page }} / {{ lastPage }}</span>
          <button
            type="button"
            class="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            :disabled="page >= lastPage"
            @click="page += 1"
          >
            {{ t("common.next") }}
          </button>
        </nav>
      </template>
    </div>
  </ConfigProvider>
</template>
