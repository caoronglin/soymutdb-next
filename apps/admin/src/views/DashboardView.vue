<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";

import { getReleases, type ReleaseSummary } from "@soymutdb/api-client";
import { formatNumber } from "@soymutdb/shared/format";
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Dashboard — the state an operator checks before touching anything: which
 * release is live, how much is in it, and whether anything is waiting.
 *
 * The counts are the release's own aggregate row, not a client-side sum over a
 * page of data: a dashboard that quietly reports "50 variants" because that is
 * the page size is worse than no dashboard.
 */
const releasesQuery = useQuery({
  queryKey: ["admin", "releases"],
  queryFn: () => getReleases({ page: 1, page_size: 50 }),
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
          <table class="mt-2 w-full text-sm" data-testid="dashboard-releases">
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
    </div>
  </ConfigProvider>
</template>
