<template>
  <div class="admin-page">
    <AdminPageHeader :title="t('admin.auditLogs')" :description="t('admin.audit.readOnly')">
      <template #meta>
        <p class="mt-2 text-sm text-muted-foreground">
          {{ t("common.total") }}: <span class="font-mono">{{ total }}</span>
        </p>
      </template>
    </AdminPageHeader>

    <form class="admin-toolbar" role="search" @submit.prevent="page = 1">
      <label class="admin-field">
        {{ t("admin.audit.action") }}
        <input
          v-model="action"
          class="admin-control admin-control--mono"
          :placeholder="t('admin.audit.actionPlaceholder')"
          data-testid="audit-action-filter"
        />
      </label>
      <label class="admin-field">
        {{ t("admin.audit.actor") }}
        <input v-model="actor" class="admin-control" data-testid="audit-actor-filter" />
      </label>
      <Button html-type="submit" size="small" data-testid="audit-apply">
        {{ t("common.apply") }}
      </Button>
      <Button
        html-type="button"
        size="small"
        :disabled="!action && !actor"
        data-testid="audit-reset"
        @click="reset"
      >
        {{ t("common.reset") }}
      </Button>
    </form>

    <AdminState v-if="query.isPending.value" state="loading" testid="audit-loading" :rows="8" />
    <AdminState
      v-else-if="query.isError.value"
      state="error"
      testid="audit-error"
      :title="t('common.errorDescription')"
    >
      <template #actions>
        <Button size="small" data-testid="audit-retry" @click="query.refetch()">
          {{ t("common.retry") }}
        </Button>
      </template>
    </AdminState>
    <AdminState
      v-else-if="items.length === 0"
      state="empty"
      testid="audit-empty"
      :title="t('common.noData')"
    />

    <AdminCard v-else>
      <div class="admin-table-wrap">
        <table class="admin-table" data-testid="audit-table">
          <thead>
            <tr>
              <th scope="col">{{ t("admin.audit.action") }}</th>
              <th scope="col">{{ t("admin.audit.actor") }}</th>
              <th scope="col">{{ t("admin.audit.resource") }}</th>
              <th scope="col">{{ t("common.date") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in items" :key="String(entry.id)" data-testid="audit-row">
              <td class="font-mono text-xs">{{ entry.action }}</td>
              <td class="text-xs">{{ entry.actor ?? "—" }}</td>
              <td class="font-mono text-xs">
                {{ entry.resource_type ?? "—"
                }}<span v-if="entry.resource_id">/{{ entry.resource_id }}</span>
              </td>
              <td class="text-xs text-muted-foreground">{{ formatDate(entry.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <template #footer>
        <Pager v-model="page" :last-page="lastPage" testid-prefix="audit" />
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
import Pager from "../components/AdminPager.vue";
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
const actor = ref("");

const query = useQuery({
  queryKey: computed(() => ["admin", "audit", page.value, action.value, actor.value]),
  queryFn: () =>
    adminApi.get<{ items: AuditEntry[]; total: number }>("/admin/audit-logs", {
      params: {
        page: page.value,
        page_size: PAGE_SIZE,
        ...(action.value ? { action: action.value } : {}),
        ...(actor.value ? { actor: actor.value } : {}),
      },
    }),
});

const items = computed(() => toValue(query.data)?.items ?? []);
const total = computed(() => toValue(query.data)?.total ?? 0);
const lastPage = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)));

function reset(): void {
  action.value = "";
  actor.value = "";
  page.value = 1;
}
</script>
