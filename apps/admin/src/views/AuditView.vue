<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { formatDate } from "@soymutdb/shared/format";
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { adminApi } from "../lib/api";
import { t } from "../lib/i18n";

/**
 * Audit log.
 *
 * Read-only on purpose: the audit trail is evidence, and an interface that can
 * edit it is an interface that can destroy it. The action filter is a free-text
 * field rather than a dropdown because the action vocabulary is owned by the
 * backend decorators, and a stale dropdown would hide new actions.
 */
interface AuditEntry {
  id: number | string;
  action: string;
  actor?: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  created_at?: string;
}

const PAGE_SIZE = 50;
const page = ref(1);
const action = ref("");

const query = useQuery({
  queryKey: computed(() => ["admin", "audit", page.value, action.value]),
  queryFn: () =>
    adminApi.get<{ items: AuditEntry[]; total: number }>("/admin/audit-logs", {
      params: { page: page.value, page_size: PAGE_SIZE, ...(action.value ? { action: action.value } : {}) },
    }),
  staleTime: 30_000,
});

const items = computed(() => toValue(query.data)?.items ?? []);
const total = computed(() => toValue(query.data)?.total ?? 0);
const lastPage = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)));
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div>
      <h1 class="text-xl font-semibold">{{ t("admin.auditLogs") }}</h1>
      <p class="mt-1 text-sm opacity-70">
        {{ t("common.total") }}: {{ total }} · read-only
      </p>

      <form class="mt-4 flex gap-2" role="search" @submit.prevent="page = 1">
        <input
          v-model="action"
          class="w-64 rounded-md border bg-background px-2 py-1.5 text-sm font-mono"
          placeholder="action"
          data-testid="audit-action-filter"
        />
        <button type="submit" class="rounded-md border px-3 py-1.5 text-sm">{{ t("common.apply") }}</button>
      </form>

      <p v-if="query.isPending.value" class="mt-4 text-sm opacity-70">{{ t("common.loading") }}</p>
      <p v-else-if="query.isError.value" data-testid="audit-error" class="mt-4 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <p v-else-if="items.length === 0" data-testid="audit-empty" class="mt-4 text-sm opacity-70">
        {{ t("common.noData") }}
      </p>
      <table v-else class="mt-4 w-full text-sm" data-testid="audit-table">
        <thead class="text-left opacity-60">
          <tr>
            <th scope="col" class="py-2">action</th>
            <th scope="col" class="py-2">actor</th>
            <th scope="col" class="py-2">resource</th>
            <th scope="col" class="py-2">{{ t("common.date") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in items" :key="String(entry.id)" class="border-t" data-testid="audit-row">
            <td class="py-2 font-mono text-xs">{{ entry.action }}</td>
            <td class="py-2 text-xs">{{ entry.actor ?? "—" }}</td>
            <td class="py-2 font-mono text-xs">
              {{ entry.resource_type ?? "—" }}<span v-if="entry.resource_id">/{{ entry.resource_id }}</span>
            </td>
            <td class="py-2 text-xs opacity-70">{{ formatDate(entry.created_at) }}</td>
          </tr>
        </tbody>
      </table>

      <nav v-if="items.length" class="mt-4 flex items-center gap-3" aria-label="Pagination">
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
    </div>
  </ConfigProvider>
</template>
