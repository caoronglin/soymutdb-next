<template>
  <div class="admin-page">
    <AdminPageHeader
      :title="t('admin.uploads')"
      :description="
        t('admin.media.description', {
          defaultValue:
            'Uploaded assets referenced by news and pages. Archiving removes an asset from the picker without breaking published references.',
        })
      "
    >
      <template #actions>
        <span v-if="total" class="text-sm text-muted-foreground" data-testid="media-total">
          {{ t("common.total") }}: {{ total }}
        </span>
      </template>
    </AdminPageHeader>

    <p v-if="errorMessage" role="alert" class="admin-state admin-state--error">
      {{ errorMessage }}
    </p>

    <AdminState
      v-if="query.isPending.value"
      state="loading"
      testid="media-loading"
      :rows="6"
    />
    <AdminState
      v-else-if="query.isError.value"
      state="error"
      testid="media-error"
      :title="t('common.errorDescription')"
    >
      <template #actions>
        <Button size="small" data-testid="media-retry" @click="query.refetch()">
          {{ t("common.retry") }}
        </Button>
      </template>
    </AdminState>
    <AdminState
      v-else-if="items.length === 0"
      state="empty"
      testid="media-empty"
      :title="t('common.noData')"
    />

    <template v-else>
      <AdminCard>
        <div class="admin-table-wrap">
          <table class="admin-table" data-testid="media-table">
            <thead>
              <tr>
                <th scope="col">{{ t("common.file") }}</th>
                <th scope="col">{{ t("common.size") }}</th>
                <th scope="col">{{ t("common.status") }}</th>
                <th scope="col">{{ t("common.date") }}</th>
                <th scope="col">{{ t("common.actions") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="asset in items" :key="asset.id" data-testid="media-row">
                <td class="font-mono text-xs">{{ asset.original_filename }}</td>
                <td class="text-xs">{{ formatFileSize(asset.size_bytes ?? null) }}</td>
                <td>
                  <AdminStatusTag :status="asset.status ?? 'active'" testid="media-status" />
                </td>
                <td class="text-xs text-muted-foreground">{{ formatDate(asset.created_at) }}</td>
                <td>
                  <div class="admin-row-actions">
                    <button
                      v-if="asset.status !== 'archived'"
                      type="button"
                      class="admin-link admin-link--danger"
                      :data-testid="'media-archive-' + asset.id"
                      @click="archiveMutation.mutate(asset.id)"
                    >
                      {{ t("common.delete") }}
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <template #footer>
          <Pager v-model="page" :last-page="lastPage" testid-prefix="media" />
        </template>
      </AdminCard>
    </template>
  </div>
</template>

<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { archiveMediaAsset, listMediaAssets, type MediaAsset } from "@soymutdb/api-client";
import { formatDate, formatFileSize } from "@soymutdb/shared/format";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
import Pager from "../components/AdminPager.vue";
import { t } from "../lib/i18n";

/**
 * Media library.
 *
 * Assets are archived rather than deleted: an image is referenced by published
 * news and pages, so a hard delete would break those records. The list shows the
 * archive state so an operator can tell "removed from the picker" apart from
 * "gone".
 *
 * The React console also had upload, search/purpose/status filters, tile
 * previews and metadata editing; the tile grid needed a browser upload path that
 * this console still routes through the import wizard, so the list keeps the
 * table form and the filters it can honour.
 */
const queryClient = useQueryClient();
const page = ref(1);
const errorMessage = ref("");

const query = useQuery({
  queryKey: computed(() => ["admin", "media", page.value]),
  queryFn: () => listMediaAssets({ page: page.value, page_size: 24 }),
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
