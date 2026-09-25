<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";
import { useRouter } from "vue-router";

import { type NewsSummary } from "@soymutdb/api-client";
import type { AssemblyInfo } from "@soymutdb/api-client";
import { cn } from "@soymutdb/shared/cn";
// Business code imports UI primitives ONLY from the facade (plan D4), never
// from antdv-next directly.
import { Button, Tag } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
import { assembliesQueryOptions, newsListQueryOptions } from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Home — the database entry point.
 *
 * The first thing on the page is the identifier search, followed by the fixed
 * set of research task entry points and the assembly catalogue. News is content
 * and sits below both: it may support the workflow, never displace it.
 */
const site = useSiteContextStore();
const router = useRouter();

const query = ref("");

const assembliesQuery = useQuery(assembliesQueryOptions());
const isPending = computed(() => toValue(assembliesQuery.isPending));
const isError = computed(() => toValue(assembliesQuery.isError));
const error = computed(() => toValue(assembliesQuery.error));
const assemblies = computed<AssemblyInfo[]>(() => toValue(assembliesQuery.data) ?? []);

const newsQuery = useQuery(newsListQueryOptions({ page: 1, pageSize: 5 }));
const news = computed<NewsSummary[]>(() => toValue(newsQuery.data)?.items ?? []);

const TASK_ENTRIES = [
  { to: "/search/genes", testId: "task-gene-search", title: "Gene ID search" },
  { to: "/search/location", testId: "task-location-search", title: "Physical location search" },
  { to: "/browser", testId: "task-jbrowse", title: "JBrowse 2" },
  { to: "/blast", testId: "task-blast", title: "BLAST" },
  { to: "/search/primer", testId: "task-primer", title: "Primer design" },
] as const;

function submitSearch() {
  const value = query.value.trim();
  if (!value) return;
  void router.push({ path: "/search", query: { q: value } });
}
</script>

<template>
  <PortalLayout>
    <div :class="cn('mx-auto max-w-5xl px-4 py-8')">
      <h1 class="text-3xl font-semibold">SoyMutDB</h1>
      <p class="mt-1 text-sm opacity-70">
        {{ t("home.subtitle") }} · {{ site.siteVariant }} ·
        {{ t("releases.title") }}: {{ site.releaseId ?? t("releases.active") }}
      </p>

      <form class="mt-6 flex flex-wrap gap-3" role="search" @submit.prevent="submitSearch">
        <label class="sr-only" for="home-search">{{ t("search.title") }}</label>
        <input
          id="home-search"
          v-model="query"
          class="w-full max-w-xl rounded-md border bg-background px-3 py-2"
          :placeholder="t('search.placeholder')"
          data-testid="home-search-input"
        />
        <Button html-type="submit" :disabled="!query.trim()" data-testid="home-search-submit">
          {{ t("common.search") }}
        </Button>
      </form>

      <section class="mt-8" aria-labelledby="task-entries-heading">
        <h2 id="task-entries-heading" class="text-lg font-medium">{{ t("home.tasks") }}</h2>
        <ul class="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="task-entries">
          <li v-for="entry in TASK_ENTRIES" :key="entry.to">
            <RouterLink
              :to="entry.to"
              class="block rounded-lg border p-4 transition hover:bg-black/5"
              :data-testid="entry.testId"
            >
              <span class="font-medium">{{ entry.title }}</span>
            </RouterLink>
          </li>
        </ul>
      </section>

      <section class="mt-8" aria-labelledby="assemblies-heading">
        <h2 id="assemblies-heading" class="text-lg font-medium">{{ t("home.assemblies") }}</h2>
        <p v-if="isPending" data-testid="assemblies-loading">{{ t("common.loading") }}</p>
        <p v-else-if="isError" data-testid="assemblies-error" class="text-red-600">
          {{ t("common.errorDescription") }}
          <span class="ms-2 font-mono text-xs">{{ (error as Error)?.message ?? "" }}</span>
        </p>
        <p v-else-if="assemblies.length === 0" data-testid="assemblies-empty">
          {{ t("common.noData") }}
        </p>
        <ul v-else data-testid="assemblies-list" class="mt-2 flex flex-col gap-2">
          <li v-for="assembly in assemblies" :key="String(assembly.id)">
            <Button type="primary" @click="site.setAssembly(assembly.name)">
              {{ assembly.name }} · {{ assembly.version }} · {{ assembly.species }}
              <Tag v-if="assembly.is_default" color="green">default</Tag>
            </Button>
          </li>
        </ul>
      </section>

      <section class="mt-8" aria-labelledby="latest-news-heading">
        <h2 id="latest-news-heading" class="text-lg font-medium">{{ t("nav.latestNews") }}</h2>
        <p v-if="news.length === 0" data-testid="home-news-empty" class="mt-2 text-sm opacity-70">
          {{ t("common.noData") }}
        </p>
        <ul v-else class="mt-2 grid gap-2" data-testid="home-news-list">
          <li v-for="item in news" :key="item.slug">
            <RouterLink :to="`/news/${item.slug}`" class="underline">
              {{ item.title_en }}
            </RouterLink>
          </li>
        </ul>
      </section>
    </div>
  </PortalLayout>
</template>
