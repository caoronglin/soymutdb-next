<template>
  <div class="admin-page">
    <AdminPageHeader
      :title="t('admin.analyticsSettings.title')"
      :description="t('admin.analyticsSettings.description')"
    />

    <form class="admin-toolbar">
      <label class="admin-field">
        {{ t("admin.analyticsSettings.window") }}
        <select v-model.number="days" class="admin-control" data-testid="analytics-days">
          <option :value="7">7</option>
          <option :value="30">30</option>
          <option :value="90">90</option>
        </select>
      </label>
    </form>

    <AdminState v-if="summaryQuery.isPending.value" state="loading" testid="analytics-loading" />
    <AdminState
      v-else-if="summaryQuery.isError.value"
      state="error"
      testid="analytics-error"
      :title="t('admin.analyticsSettings.loadError')"
    >
      <template #actions>
        <Button size="small" data-testid="analytics-retry" @click="summaryQuery.refetch()">
          {{ t("common.retry") }}
        </Button>
      </template>
    </AdminState>

    <template v-else-if="summary">
      <div class="grid gap-4 sm:grid-cols-2" data-testid="analytics-summary">
        <AdminStatCard
          :label="t('admin.analyticsSettings.totalEvents')"
          :value="String(summary.total_events)"
          testid="analytics-total-events"
        />
        <AdminStatCard
          :label="t('admin.analyticsSettings.uniqueSessions')"
          :value="String(summary.unique_sessions)"
          testid="analytics-unique-sessions"
        />
      </div>

      <!-- A zero here is a real answer ("nobody visited"), so it is labelled
           rather than left to read as a missing value. -->
      <p
        v-if="summary.total_events === 0"
        class="admin-state admin-state--empty"
        data-testid="analytics-empty"
      >
        {{ t("admin.analyticsSettings.description") }}
      </p>

      <AdminCard>
        <div class="grid gap-6 sm:grid-cols-2">
          <div v-for="block in BREAKDOWNS" :key="block.testid" :data-testid="block.testid">
            <h2 class="admin-section-title">{{ t(block.titleKey) }}</h2>
            <p
              v-if="summary[block.field].length === 0"
              class="mt-1 text-xs text-muted-foreground"
            >
              {{ t("common.noData") }}
            </p>
            <ul v-else class="mt-2 grid gap-1 text-sm">
              <li
                v-for="item in summary[block.field]"
                :key="item.label"
                class="flex items-baseline justify-between gap-3 border-b border-border/60 pb-1 last:border-0"
              >
                <span class="truncate font-mono text-xs">{{ item.label }}</span>
                <span class="shrink-0 text-xs">{{ item.count }}</span>
              </li>
            </ul>
          </div>
        </div>
      </AdminCard>
    </template>

    <AdminCard
      :title="t('admin.analyticsSettings.overviewTitle')"
      testid="analytics-cloudflare"
    >
      <template #actions>
        <AdminStatusTag status="active" />
      </template>
      <p class="text-sm text-muted-foreground">{{ t("admin.analyticsSettings.overviewDesc") }}</p>
      <p class="mt-2 text-sm text-muted-foreground">{{ t("admin.analyticsSettings.beaconNote") }}</p>
      <p class="mt-3 flex flex-wrap items-center gap-3">
        <code class="rounded-md border border-border bg-muted px-2 py-1 font-mono text-xs">
          {{ CLOUDFLARE_ENV_VAR }}
        </code>
        <a
          :href="CLOUDFLARE_DASHBOARD_URL"
          target="_blank"
          rel="noopener noreferrer"
          class="admin-link"
        >
          {{ t("admin.analyticsSettings.dashboardLink") }}
        </a>
      </p>
    </AdminCard>
  </div>
</template>

<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { getAdminAnalyticsSummary } from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatCard from "../components/AdminStatCard.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
import { t } from "../lib/i18n";

/**
 * Analytics settings.
 *
 * The console half of visitor analytics: the aggregate numbers come from the
 * administrator endpoint `GET /admin/analytics/summary` (ClickHouse-backed), and
 * the public-portal Cloudflare beacon is documented here because its token is a
 * build-time `VITE_*` value this page cannot read back from the running
 * deployment. Nothing on this page is hard-coded sample data: when the endpoint
 * is unavailable the view says so instead of showing zeros that read as "no
 * traffic".
 */
const days = ref(7);

const summaryQuery = useQuery({
  queryKey: computed(() => ["admin", "analytics", "summary", days.value]),
  queryFn: () => getAdminAnalyticsSummary({ days: days.value }),
});

const summary = computed(() => toValue(summaryQuery.data));

/** One row per server-provided breakdown; the four blocks are the same shape. */
const BREAKDOWNS = [
  {
    field: "events_by_type" as const,
    testid: "analytics-by-type",
    titleKey: "admin.analyticsSettings.byType",
  },
  {
    field: "top_pages" as const,
    testid: "analytics-top-pages",
    titleKey: "admin.analyticsSettings.topPages",
  },
  {
    field: "top_searches" as const,
    testid: "analytics-top-searches",
    titleKey: "admin.analyticsSettings.topSearches",
  },
  {
    field: "top_referrers" as const,
    testid: "analytics-top-referrers",
    titleKey: "admin.analyticsSettings.topReferrers",
  },
];

const CLOUDFLARE_ENV_VAR = "VITE_CLOUDFLARE_ANALYTICS_TOKEN";
const CLOUDFLARE_DASHBOARD_URL = "https://dash.cloudflare.com/?to=/:account/web-analytics";
</script>
