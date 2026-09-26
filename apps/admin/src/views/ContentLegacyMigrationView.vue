<script setup lang="ts">
import { useMutation } from "@tanstack/vue-query";
import { computed, toValue } from "vue";

import {
  dryRunStaticPageMigration,
  type StaticPageMigrationDryRunReport,
} from "@soymutdb/api-client";
import { Button, ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

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

const report = computed<StaticPageMigrationDryRunReport | undefined>(() =>
  toValue(preview.data),
);
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="max-w-4xl">
      <h1 class="text-xl font-semibold">{{ t("admin.contentLegacy.title") }}</h1>
      <p class="mt-2 text-sm opacity-70">{{ t("admin.contentLegacy.description") }}</p>
      <p class="mt-3 rounded-md border border-border bg-muted px-3 py-2 text-sm" data-testid="migration-note">
        {{ t("admin.contentLegacy.readOnly") }}
      </p>

      <div class="mt-4">
        <Button :disabled="preview.isPending.value" data-testid="migration-run" @click="preview.mutate()">
          {{ t("admin.contentLegacy.preview") }}
        </Button>
      </div>

      <p v-if="preview.isError.value" role="alert" class="mt-4 text-sm text-red-700" data-testid="migration-error">
        {{ t("common.errorDescription") }}
      </p>

      <div v-if="report" class="mt-5" data-testid="migration-report">
        <p class="text-sm">
          {{ t("admin.contentLegacy.summary", {
            created: report.created,
            skipped: report.skipped,
            invalid: report.invalid,
          }) }}
        </p>
        <p v-if="report.items.length === 0" class="mt-3 text-sm opacity-70" data-testid="migration-empty">
          {{ t("admin.contentLegacy.empty") }}
        </p>
        <table v-else class="mt-3 w-full text-left text-sm">
          <thead class="text-left opacity-60">
            <tr>
              <th scope="col" class="p-2">{{ t("admin.contentLegacy.slug") }}</th>
              <th scope="col" class="p-2">{{ t("admin.contentLegacy.route") }}</th>
              <th scope="col" class="p-2">{{ t("admin.contentLegacy.outcome") }}</th>
              <th scope="col" class="p-2">{{ t("admin.contentLegacy.message") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in report.items"
              :key="item.static_page_id"
              class="border-t"
              data-testid="migration-item"
            >
              <td class="p-2 font-mono text-xs">{{ item.slug }}</td>
              <td class="p-2 font-mono text-xs">{{ item.route }}</td>
              <td class="p-2">{{ item.outcome }}</td>
              <td class="p-2 opacity-70">
                {{ item.message ?? t("admin.contentLegacy.ready") }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </ConfigProvider>
</template>
