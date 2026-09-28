<template>
  <div class="admin-page">
    <AdminPageHeader
      :title="t('admin.contentLegacy.title')"
      :description="t('admin.contentLegacy.description')"
    >
      <template #actions>
        <Button data-testid="migration-run" :disabled="preview.isPending.value" @click="preview.mutate()">
          {{ preview.isPending.value ? t("common.loading") : t("admin.contentLegacy.preview") }}
        </Button>
      </template>
    </AdminPageHeader>

    <p class="admin-state" data-testid="migration-note">
      {{ t("admin.contentLegacy.readOnly") }}
    </p>

    <AdminState
      v-if="preview.isError.value"
      state="error"
      testid="migration-error"
      :title="t('common.errorDescription')"
    />

    <template v-if="preview.isPending.value">
      <AdminState state="loading" testid="migration-loading" :rows="4" />
    </template>

    <AdminCard v-else-if="report" testid="migration-report">
      <p class="text-sm">
        {{ t("admin.contentLegacy.summary", {
          created: report.created,
          skipped: report.skipped,
          invalid: report.invalid,
        }) }}
      </p>

      <p v-if="report.items.length === 0" class="mt-3 text-sm text-muted-foreground" data-testid="migration-empty">
        {{ t("admin.contentLegacy.empty") }}
      </p>
      <div v-else class="admin-table-wrap mt-3">
        <table class="admin-table">
          <thead>
            <tr>
              <th scope="col">{{ t("admin.contentLegacy.slug") }}</th>
              <th scope="col">{{ t("admin.contentLegacy.route") }}</th>
              <th scope="col">{{ t("admin.contentLegacy.outcome") }}</th>
              <th scope="col">{{ t("admin.contentLegacy.message") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in report.items" :key="item.static_page_id" data-testid="migration-item">
              <td class="font-mono text-xs">{{ item.slug }}</td>
              <td class="font-mono text-xs">{{ item.route }}</td>
              <td><AdminStatusTag :status="item.outcome" /></td>
              <td class="text-muted-foreground">
                {{ item.message ?? t("admin.contentLegacy.ready") }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </AdminCard>
  </div>
</template>

<script setup lang="ts">
import { useMutation } from "@tanstack/vue-query";
import { computed, toValue } from "vue";

import {
  dryRunStaticPageMigration,
  type StaticPageMigrationDryRunReport,
} from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
import { t } from "../lib/i18n";

/**
 * Legacy static-page migration preview (read-only).
 *
 * The only backing endpoint is
 * `POST /admin/content/pages/migrate-to-page-builder/dry-run`, which reports
 * which legacy pages could become page-builder drafts. It is a dry run by
 * contract: it never creates, publishes, or mutates a page, and every row is a
 * server response. ADR-0009 retires the page builder itself, so this page is a
 * migration diagnostic only; it exposes no editor and performs no writes.
 */
const preview = useMutation({
  mutationFn: () => dryRunStaticPageMigration({}),
});

const report = computed<StaticPageMigrationDryRunReport | undefined>(() => toValue(preview.data));
</script>
