<template>
  <div class="admin-page">
    <AdminPageHeader :title="t('admin.imports')" :description="t('admin.importsHint', { defaultValue: 'Every import task this deployment has accepted, server-filtered by status.' })">
      <template #actions>
        <RouterLink
          to="/imports/new"
          class="inline-flex min-h-9 items-center rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground"
          data-testid="imports-new"
        >
          {{ t("admin.importCreate.title") }}
        </RouterLink>
      </template>
    </AdminPageHeader>

    <form class="admin-toolbar" @submit.prevent="page = 1">
      <label class="admin-field">
        {{ t("common.status") }}
        <select
          v-model="status"
          class="admin-control"
          data-testid="imports-status-filter"
          @change="page = 1"
        >
          <option value="">{{ t("common.all") }}</option>
          <option v-for="value in STATUSES" :key="value" :value="value">{{ value }}</option>
        </select>
      </label>
      <span v-if="total" class="text-sm text-muted-foreground" data-testid="imports-total">
        {{ t("common.total") }}: {{ total }}
      </span>
    </form>

    <AdminState v-if="query.isPending.value" state="loading" testid="imports-loading" :rows="6" />
    <AdminState
      v-else-if="query.isError.value"
      state="error"
      testid="imports-error"
      :title="t('common.errorDescription')"
    >
      <template #actions>
        <Button size="small" data-testid="imports-retry" @click="query.refetch()">
          {{ t("common.retry") }}
        </Button>
      </template>
    </AdminState>
    <AdminState
      v-else-if="items.length === 0"
      state="empty"
      testid="imports-empty"
      :title="t('common.noData')"
    />

    <AdminCard v-else>
      <div class="admin-table-wrap">
        <table class="admin-table" data-testid="imports-table">
          <thead>
            <tr>
              <th scope="col">{{ t("common.file") }}</th>
              <th scope="col">{{ t("common.status") }}</th>
              <th scope="col">{{ t("common.date") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in items" :key="task.id" data-testid="import-row">
              <td class="font-mono text-xs">
                <RouterLink
                  :to="`/imports/${task.id}`"
                  class="admin-link"
                  data-testid="import-detail-link"
                >
                  {{ task.filename }}
                </RouterLink>
              </td>
              <td data-testid="import-status">
                <AdminStatusTag :status="task.status" />
              </td>
              <td class="text-xs text-muted-foreground">{{ formatDate(task.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <template #footer>
        <Pager v-model="page" :last-page="lastPage" testid-prefix="imports" />
      </template>
    </AdminCard>
  </div>
</template>

<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { formatDate } from "@soymutdb/shared/format";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
import Pager from "../components/AdminPager.vue";
import { adminApi } from "../lib/api";
import { t } from "../lib/i18n";

/**
 * Import tasks — what has been ingested, and what state it is in.
 *
 * The list is server-paginated and filterable by status, because "did last
 * night's import finish?" is a question about a specific status, not about the
 * newest 20 rows. A task is never shown as successful from a client-side
 * assumption: the status column is the server's.
 */
interface ImportTaskRow {
  id: number;
  filename: string;
  type: string;
  status: string;
  created_at?: string;
}

interface ImportListResponse {
  items: ImportTaskRow[];
  total: number;
}

const PAGE_SIZE = 20;
const page = ref(1);
const status = ref("");

const query = useQuery({
  queryKey: computed(() => ["admin", "imports", page.value, status.value]),
  queryFn: () =>
    adminApi.get<ImportListResponse>("/admin/imports", {
      params: {
        page: page.value,
        page_size: PAGE_SIZE,
        ...(status.value ? { status: status.value } : {}),
      },
    }),
});

const items = computed(() => toValue(query.data)?.items ?? []);
const total = computed(() => toValue(query.data)?.total ?? 0);
const lastPage = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)));
const STATUSES = ["pending", "running", "processing", "completed", "failed", "cancelled"] as const;
</script>
