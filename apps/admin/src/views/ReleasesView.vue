<template>
  <div class="admin-page">
    <AdminPageHeader
      :title="t('admin.releases')"
      :description="
        t('admin.releasesHint', {
          defaultValue:
            'Every release the API serves, with the imports and source files that produced it.',
        })
      "
    />

    <AdminState v-if="query.isPending.value" state="loading" testid="releases-loading" :rows="5" />
    <AdminState
      v-else-if="query.isError.value"
      state="error"
      testid="releases-error"
      :title="t('common.errorDescription')"
    >
      <template #actions>
        <Button size="small" data-testid="releases-retry" @click="query.refetch()">
          {{ t("common.retry") }}
        </Button>
      </template>
    </AdminState>
    <AdminState
      v-else-if="releases.length === 0"
      state="empty"
      testid="releases-empty"
      :title="t('common.noData')"
    />

    <AdminCard v-else>
      <div class="admin-table-wrap">
        <table class="admin-table" data-testid="releases-table">
          <thead>
            <tr>
              <th scope="col">{{ t("releases.releaseName") }}</th>
              <th scope="col">{{ t("releases.status") }}</th>
              <th scope="col">{{ t("releases.assembly") }}</th>
              <th scope="col" class="admin-table-num">{{ t("releases.variantCount") }}</th>
              <th scope="col">{{ t("common.actions") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="release in releases" :key="String(release.id)" data-testid="release-row">
              <td class="font-mono text-xs">
                {{ release.id }}
                <span v-if="release.is_active" class="ms-2 text-xs text-primary">
                  {{ t("releases.active") }}
                </span>
              </td>
              <td><AdminStatusTag :status="release.status" /></td>
              <td class="font-mono text-xs">{{ release.assembly_name }}</td>
              <td class="admin-table-num">{{ formatNumber(release.variant_count) }}</td>
              <td>
                <button
                  type="button"
                  class="admin-link"
                  :data-testid="'release-provenance-' + release.id"
                  @click="selectedId = String(release.id)"
                >
                  {{ t("releases.provenance") }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </AdminCard>

    <AdminCard v-if="selectedId">
      <template #actions>
        <Button size="small" data-testid="provenance-close" @click="selectedId = null">
          {{ t("common.close") }}
        </Button>
      </template>
      <h2 class="admin-section-title" data-testid="provenance-heading">
        {{ t("releases.provenance") }} · <span class="font-mono">{{ selectedId }}</span>
      </h2>

      <AdminState
        v-if="provenanceQuery.isPending.value"
        state="loading"
        testid="provenance-loading"
        class="mt-3"
      />
      <AdminState
        v-else-if="provenanceQuery.isError.value"
        state="error"
        testid="provenance-error"
        class="mt-3"
        :title="t('common.errorDescription')"
      />
      <AdminState
        v-else-if="provenance.length === 0"
        state="empty"
        testid="provenance-empty"
        class="mt-3"
        :title="t('common.noData')"
      />
      <ul v-else class="mt-3 grid gap-2" data-testid="provenance-list">
        <li v-for="item in provenance" :key="String(item.id)" class="rounded-md border border-border p-3 text-sm">
          <p class="font-mono text-xs">{{ item.source_type }} · {{ item.source_name }}</p>
          <p v-if="item.version" class="mt-1 text-xs text-muted-foreground">{{ item.version }}</p>
          <a
            v-if="item.source_url"
            :href="item.source_url"
            target="_blank"
            rel="noopener noreferrer"
            class="admin-link mt-1 inline-block"
          >
            {{ item.source_url }}
          </a>
        </li>
      </ul>
    </AdminCard>
  </div>
</template>

<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { getReleaseProvenance, getReleases } from "@soymutdb/api-client";
import { formatNumber } from "@soymutdb/shared/format";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
import { t } from "../lib/i18n";

/**
 * Releases — where each published release came from.
 *
 * A release row is only half the record: an operator publishing data needs to
 * see the provenance (which imports, which source files) that produced it. The
 * provenance is fetched per release on demand rather than for every row, so
 * opening this page does not fan out into one request per release.
 */
const query = useQuery({
  queryKey: ["admin", "releases"],
  queryFn: () => getReleases({ page: 1, page_size: 100 }),
});

const releases = computed(() => toValue(query.data) ?? []);
const selectedId = ref<string | null>(null);

const provenanceQuery = useQuery({
  queryKey: computed(() => ["admin", "release-provenance", selectedId.value]),
  queryFn: () => getReleaseProvenance(selectedId.value as string),
  enabled: computed(() => Boolean(selectedId.value)),
});
const provenance = computed(() => toValue(provenanceQuery.data) ?? []);
</script>
