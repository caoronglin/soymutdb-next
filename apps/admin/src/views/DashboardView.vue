<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import {
  getAdminAnalyticsSummary,
  getReleases,
  type ReleaseSummary,
} from "@soymutdb/api-client";
import { formatNumber } from "@soymutdb/shared/format";
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Dashboard — the state an operator checks before touching anything: which
 * release is live, how much is in it, and whether anything is waiting.
 *
 * The counts are the release's own aggregate row, not a client-side sum over a
 * page of data: a dashboard that quietly reports "50 variants" because that is
 * the page size is worse than no dashboard. The visitor summary comes from the
 * administrator endpoint `GET /admin/analytics/summary` (ClickHouse-backed).
 * Every number on the page is served by the API — there are no sample or
 * placeholder values, and each section states loading/error/empty explicitly.
 */
const releasesQuery = useQuery({
  queryKey: ["admin", "releases"],
  queryFn: () => getReleases({ page: 1, page_size: 50 }),
  staleTime: 30_000,
});

const analyticsDays = ref(7);
const analyticsQuery = useQuery({
  queryKey: computed(() => ["admin", "analytics", "summary", analyticsDays.value]),
  queryFn: () => getAdminAnalyticsSummary({ days: analyticsDays.value }),
  staleTime: 30_000,
});

const releases = computed(() => toValue(releasesQuery.data) ?? []);
/**
 * The active release comes from the list the API already returns (`is_active`),
 * not from a second endpoint: there is no `GET /releases/current`, and a
 * dashboard that 422s on load is worse than one that reads a field it has.
 */
const activeRelease = computed<ReleaseSummary | null>(
  () => releases.value.find((release) => release.is_active) ?? null,
);
const analytics = computed(() => toValue(analyticsQuery.data));
const analyticsHasTraffic = computed(
  () => analytics.value !== undefined && analytics.value.total_events > 0,
);
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div>
      <h1 class="text-xl font-semibold">{{ t("admin.dashboard") }}</h1>

      <p v-if="releasesQuery.isPending.value" data-testid="dashboard-loading" class="mt-4 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <p v-else-if="releasesQuery.isError.value" data-testid="dashboard-error" class="mt-4 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <template v-else>
        <section class="mt-6" aria-labelledby="active-release-heading">
          <h2 id="active-release-heading" class="text-sm font-medium opacity-70">
            {{ t("releases.active") }}
          </h2>
          <p v-if="!activeRelease" data-testid="dashboard-no-active" class="mt-1 text-sm">
            {{ t("common.noData") }}
          </p>
          <dl v-else class="mt-2 grid gap-4 sm:grid-cols-3" data-testid="dashboard-active">
            <div>
              <dt class="text-xs opacity-70">{{ t("releases.releaseName") }}</dt>
              <dd class="font-mono" data-testid="dashboard-release-id">{{ activeRelease.id }}</dd>
            </div>
            <div>
              <dt class="text-xs opacity-70">{{ t("releases.status") }}</dt>
              <dd>{{ activeRelease.status }}</dd>
            </div>
            <div>
              <dt class="text-xs opacity-70">{{ t("releases.assembly") }}</dt>
              <dd class="font-mono">{{ activeRelease.assembly_name }}</dd>
            </div>
            <div>
              <dt class="text-xs opacity-70">{{ t("releases.variantCount") }}</dt>
              <dd data-testid="dashboard-variants">{{ formatNumber(activeRelease.variant_count) }}</dd>
            </div>
            <div>
              <dt class="text-xs opacity-70">{{ t("releases.geneCount") }}</dt>
              <dd>{{ formatNumber(activeRelease.gene_count) }}</dd>
            </div>
            <div>
              <dt class="text-xs opacity-70">{{ t("releases.mutantLineCount") }}</dt>
              <dd>{{ formatNumber(activeRelease.mutant_line_count) }}</dd>
            </div>
          </dl>
        </section>

        <section class="mt-8" aria-labelledby="releases-heading">
          <h2 id="releases-heading" class="text-sm font-medium opacity-70">{{ t("admin.releases") }}</h2>
          <p
            v-if="releases.length === 0"
            data-testid="dashboard-releases-empty"
            class="mt-2 text-sm opacity-70"
          >
            {{ t("admin.dashboardStats.releasesEmpty") }}
          </p>
          <table v-else class="mt-2 w-full text-sm" data-testid="dashboard-releases">
            <thead class="text-left opacity-60">
              <tr>
                <th scope="col" class="py-2">{{ t("releases.releaseName") }}</th>
                <th scope="col" class="py-2">{{ t("releases.status") }}</th>
                <th scope="col" class="py-2">{{ t("releases.assembly") }}</th>
                <th scope="col" class="py-2 text-right">{{ t("releases.variantCount") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="release in releases" :key="String(release.id)" class="border-t" data-testid="dashboard-release-row">
                <td class="py-2 font-mono">
                  {{ release.id }}
                  <span v-if="release.is_active" class="ms-2 text-xs opacity-70">
                    ({{ t("releases.active") }})
                  </span>
                </td>
                <td class="py-2">{{ release.status }}</td>
                <td class="py-2 font-mono text-xs">{{ release.assembly_name }}</td>
                <td class="py-2 text-right">{{ formatNumber(release.variant_count) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>

      <section class="mt-8" aria-labelledby="dashboard-analytics-heading" data-testid="dashboard-analytics">
        <div class="flex flex-wrap items-end gap-3">
          <h2 id="dashboard-analytics-heading" class="text-sm font-medium opacity-70">
            {{ t("admin.dashboardStats.analyticsHeading") }}
          </h2>
          <label class="text-sm opacity-70">
            {{ t("admin.dashboardStats.windowLabel") }}
            <select
              v-model.number="analyticsDays"
              class="ms-2 rounded-md border bg-background px-2 py-1.5"
              data-testid="dashboard-analytics-days"
            >
              <option :value="7">7</option>
              <option :value="30">30</option>
              <option :value="90">90</option>
            </select>
          </label>
        </div>

        <p v-if="analyticsQuery.isPending.value" class="mt-2 text-sm opacity-70">
          {{ t("common.loading") }}
        </p>
        <p
          v-else-if="analyticsQuery.isError.value"
          role="alert"
          class="mt-2 text-sm text-red-700"
          data-testid="dashboard-analytics-error"
        >
          {{ t("admin.dashboardStats.analyticsError") }}
        </p>
        <p
          v-else-if="!analyticsHasTraffic"
          class="mt-2 text-sm opacity-70"
          data-testid="dashboard-analytics-empty"
        >
          {{ t("admin.dashboardStats.analyticsEmpty") }}
        </p>
        <template v-else>
          <dl class="mt-2 grid gap-4 sm:grid-cols-2" data-testid="dashboard-analytics-summary">
            <div class="rounded-lg border p-4">
              <dt class="text-xs uppercase opacity-60">{{ t("admin.analyticsSettings.totalEvents") }}</dt>
              <dd class="mt-1 text-2xl font-semibold" data-testid="dashboard-analytics-total-events">
                {{ analytics?.total_events }}
              </dd>
            </div>
            <div class="rounded-lg border p-4">
              <dt class="text-xs uppercase opacity-60">{{ t("admin.analyticsSettings.uniqueSessions") }}</dt>
              <dd class="mt-1 text-2xl font-semibold" data-testid="dashboard-analytics-unique-sessions">
                {{ analytics?.unique_sessions }}
              </dd>
            </div>
          </dl>
          <div v-if="analytics && analytics.top_pages.length" class="mt-4">
            <h3 class="text-xs uppercase opacity-60">{{ t("admin.analyticsSettings.topPages") }}</h3>
            <ul class="mt-1 grid gap-1 text-sm">
              <li
                v-for="item in analytics.top_pages.slice(0, 5)"
                :key="item.label"
                class="flex justify-between"
              >
                <span class="truncate font-mono text-xs">{{ item.label }}</span>
                <span>{{ item.count }}</span>
              </li>
            </ul>
          </div>
        </template>
      </section>
    </div>
  </ConfigProvider>
</template>
