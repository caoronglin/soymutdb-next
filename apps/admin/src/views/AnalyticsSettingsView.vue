<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { getAdminAnalyticsSummary } from "@soymutdb/api-client";
import { ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Analytics settings.
 *
 * The console half of visitor analytics: the aggregate numbers come from the
 * administrator endpoint `GET /admin/analytics/summary` (ClickHouse-backed),
 * and the public-portal Cloudflare beacon is documented here because its token
 * is a build-time `VITE_*` value that this page cannot read back from the
 * running deployment. Nothing on this page is hard-coded sample data: when the
 * endpoint is unavailable the view says so instead of showing zeros that read
 * as "no traffic".
 */
const days = ref(7);

const summaryQuery = useQuery({
  queryKey: computed(() => ["admin", "analytics", "summary", days.value]),
  queryFn: () => getAdminAnalyticsSummary({ days: days.value }),
  staleTime: 30_000,
});

const summary = computed(() => toValue(summaryQuery.data));

const CLOUDFLARE_ENV_VAR = "VITE_CLOUDFLARE_ANALYTICS_TOKEN";
const CLOUDFLARE_DASHBOARD_URL = "https://dash.cloudflare.com/?to=/:account/web-analytics";
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="max-w-4xl">
      <h1 class="text-xl font-semibold">{{ t("admin.analyticsSettings.title") }}</h1>
      <p class="mt-2 text-sm opacity-70">{{ t("admin.analyticsSettings.description") }}</p>

      <div class="mt-4 flex flex-wrap items-end gap-3">
        <label class="text-sm opacity-70">
          {{ t("admin.analyticsSettings.window") }}
          <select
            v-model.number="days"
            class="ms-2 rounded-md border bg-background px-2 py-1.5"
            data-testid="analytics-days"
          >
            <option :value="7">7</option>
            <option :value="30">30</option>
            <option :value="90">90</option>
          </select>
        </label>
      </div>

      <p v-if="summaryQuery.isPending.value" class="mt-4 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <p
        v-else-if="summaryQuery.isError.value"
        role="alert"
        class="mt-4 rounded-md border border-red-200 p-3 text-sm text-red-700"
        data-testid="analytics-error"
      >
        {{ t("admin.analyticsSettings.loadError") }}
      </p>
      <div v-else-if="summary" class="mt-4" data-testid="analytics-summary">
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="rounded-lg border p-4">
            <p class="text-xs uppercase opacity-60">{{ t("admin.analyticsSettings.totalEvents") }}</p>
            <p class="mt-1 text-2xl font-semibold" data-testid="analytics-total-events">
              {{ summary.total_events }}
            </p>
          </div>
          <div class="rounded-lg border p-4">
            <p class="text-xs uppercase opacity-60">{{ t("admin.analyticsSettings.uniqueSessions") }}</p>
            <p class="mt-1 text-2xl font-semibold" data-testid="analytics-unique-sessions">
              {{ summary.unique_sessions }}
            </p>
          </div>
        </div>

        <section class="mt-5 grid gap-5 sm:grid-cols-2">
          <div data-testid="analytics-by-type">
            <h2 class="text-sm font-medium">{{ t("admin.analyticsSettings.byType") }}</h2>
            <p v-if="summary.events_by_type.length === 0" class="mt-1 text-xs opacity-60">
              {{ t("common.noData") }}
            </p>
            <ul v-else class="mt-1 grid gap-1 text-sm">
              <li v-for="item in summary.events_by_type" :key="item.label" class="flex justify-between">
                <span class="font-mono text-xs">{{ item.label }}</span>
                <span>{{ item.count }}</span>
              </li>
            </ul>
          </div>

          <div data-testid="analytics-top-pages">
            <h2 class="text-sm font-medium">{{ t("admin.analyticsSettings.topPages") }}</h2>
            <p v-if="summary.top_pages.length === 0" class="mt-1 text-xs opacity-60">
              {{ t("common.noData") }}
            </p>
            <ul v-else class="mt-1 grid gap-1 text-sm">
              <li v-for="item in summary.top_pages" :key="item.label" class="flex justify-between">
                <span class="truncate font-mono text-xs">{{ item.label }}</span>
                <span>{{ item.count }}</span>
              </li>
            </ul>
          </div>

          <div data-testid="analytics-top-searches">
            <h2 class="text-sm font-medium">{{ t("admin.analyticsSettings.topSearches") }}</h2>
            <p v-if="summary.top_searches.length === 0" class="mt-1 text-xs opacity-60">
              {{ t("common.noData") }}
            </p>
            <ul v-else class="mt-1 grid gap-1 text-sm">
              <li v-for="item in summary.top_searches" :key="item.label" class="flex justify-between">
                <span class="truncate font-mono text-xs">{{ item.label }}</span>
                <span>{{ item.count }}</span>
              </li>
            </ul>
          </div>

          <div data-testid="analytics-top-referrers">
            <h2 class="text-sm font-medium">{{ t("admin.analyticsSettings.topReferrers") }}</h2>
            <p v-if="summary.top_referrers.length === 0" class="mt-1 text-xs opacity-60">
              {{ t("common.noData") }}
            </p>
            <ul v-else class="mt-1 grid gap-1 text-sm">
              <li v-for="item in summary.top_referrers" :key="item.label" class="flex justify-between">
                <span class="truncate font-mono text-xs">{{ item.label }}</span>
                <span>{{ item.count }}</span>
              </li>
            </ul>
          </div>
        </section>
      </div>

      <section class="mt-8 rounded-lg border p-4" data-testid="analytics-cloudflare">
        <h2 class="text-sm font-medium">
          {{ t("admin.analyticsSettings.overviewTitle") }}
          <Tag color="blue">{{ t("admin.analyticsSettings.cloudflareBadge") }}</Tag>
        </h2>
        <p class="mt-2 text-sm opacity-70">{{ t("admin.analyticsSettings.overviewDesc") }}</p>
        <p class="mt-2 text-sm opacity-70">{{ t("admin.analyticsSettings.beaconNote") }}</p>
        <p class="mt-3 flex flex-wrap items-center gap-3">
          <code class="rounded-md border bg-muted px-2 py-1 font-mono text-xs">{{ CLOUDFLARE_ENV_VAR }}</code>
          <a
            :href="CLOUDFLARE_DASHBOARD_URL"
            target="_blank"
            rel="noopener noreferrer"
            class="text-sm text-primary underline"
          >
            {{ t("admin.analyticsSettings.dashboardLink") }}
          </a>
        </p>
      </section>
    </div>
  </ConfigProvider>
</template>
