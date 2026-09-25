<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { formatDate } from "@soymutdb/shared/format";
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

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
  page: number;
  page_size: number;
}

const PAGE_SIZE = 20;
const page = ref(1);
const status = ref("");

const query = useQuery({
  queryKey: computed(() => ["admin", "imports", page.value, status.value]),
  queryFn: () =>
    adminApi.get<ImportListResponse>("/admin/imports", {
      params: { page: page.value, page_size: PAGE_SIZE, ...(status.value ? { status: status.value } : {}) },
    }),
  staleTime: 15_000,
});

const items = computed(() => toValue(query.data)?.items ?? []);
const total = computed(() => toValue(query.data)?.total ?? 0);
const lastPage = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)));
const STATUSES = ["pending", "running", "processing", "completed", "failed", "cancelled"] as const;
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div>
      <h1 class="text-xl font-semibold">{{ t("admin.imports") }}</h1>

      <form class="mt-4 flex flex-wrap items-end gap-3" @submit.prevent="page = 1">
        <label class="text-sm opacity-70">
          {{ t("common.status") }}
          <select
            v-model="status"
            class="mt-1 rounded-md border bg-background px-2 py-1.5"
            data-testid="imports-status-filter"
            @change="page = 1"
          >
            <option value="">{{ t("common.all") }}</option>
            <option v-for="value in STATUSES" :key="value" :value="value">{{ value }}</option>
          </select>
        </label>
      </form>

      <p v-if="query.isPending.value" class="mt-4 text-sm opacity-70">{{ t("common.loading") }}</p>
      <p v-else-if="query.isError.value" data-testid="imports-error" class="mt-4 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <p v-else-if="items.length === 0" data-testid="imports-empty" class="mt-4 text-sm opacity-70">
        {{ t("common.noData") }}
      </p>
      <template v-else>
        <p class="mt-4 text-sm opacity-70" data-testid="imports-total">
          {{ t("common.total") }}: {{ total }}
        </p>
        <table class="mt-2 w-full text-sm" data-testid="imports-table">
          <thead class="text-left opacity-60">
            <tr>
              <th scope="col" class="py-2">{{ t("common.file") }}</th>
              <th scope="col" class="py-2">{{ t("common.status") }}</th>
              <th scope="col" class="py-2">{{ t("common.date") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in items" :key="task.id" class="border-t" data-testid="import-row">
              <td class="py-2 font-mono text-xs">{{ task.filename }}</td>
              <td class="py-2" data-testid="import-status">{{ task.status }}</td>
              <td class="py-2 text-xs opacity-70">{{ formatDate(task.created_at) }}</td>
            </tr>
          </tbody>
        </table>
        <nav class="mt-4 flex items-center gap-3" aria-label="Pagination">
          <button
            type="button"
            class="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            :disabled="page <= 1"
            data-testid="imports-prev"
            @click="page -= 1"
          >
            {{ t("common.previous") }}
          </button>
          <span class="text-sm opacity-70" data-testid="imports-page">{{ page }} / {{ lastPage }}</span>
          <button
            type="button"
            class="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            :disabled="page >= lastPage"
            data-testid="imports-next"
            @click="page += 1"
          >
            {{ t("common.next") }}
          </button>
        </nav>
      </template>
    </div>
  </ConfigProvider>
</template>
