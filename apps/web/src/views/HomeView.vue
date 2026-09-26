<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";
import { useRouter } from "vue-router";

import type { AssemblyInfo, NewsSummary } from "@soymutdb/api-client";
import { Button, Tag } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { currentLanguage, t } from "../lib/i18n";
import { assembliesQueryOptions, featuredNewsQueryOptions } from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

const site = useSiteContextStore();
const router = useRouter();
const query = ref("");

const assembliesQuery = useQuery(assembliesQueryOptions());
const assemblies = computed<AssemblyInfo[]>(() => toValue(assembliesQuery.data) ?? []);
const selectedAssembly = computed(() =>
  assemblies.value.find((assembly) => String(assembly.id) === site.assemblyKey),
);

const newsQuery = useQuery(featuredNewsQueryOptions());
const news = computed<NewsSummary[]>(() => toValue(newsQuery.data)?.featured?.slice(0, 5) ?? []);

const DATABASE_ENTRIES = [
  {
    key: "genes",
    to: "/genes",
    titleKey: "home.database.genes",
    descriptionKey: "home.database.genesDescription",
  },
  {
    key: "variants",
    to: "/variants",
    titleKey: "home.database.variants",
    descriptionKey: "home.database.variantsDescription",
  },
  {
    key: "mutants",
    to: "/mutants",
    titleKey: "home.database.mutants",
    descriptionKey: "home.database.mutantsDescription",
  },
] as const;

const TASK_ENTRIES = [
  { to: "/search/genes", testId: "task-gene-search", titleKey: "home.toolGeneLabel", descriptionKey: "home.toolGeneDescription" },
  { to: "/search/location", testId: "task-location-search", titleKey: "home.toolLocationLabel", descriptionKey: "home.toolLocationDescription" },
  { to: "/search/gbrowse", testId: "task-jbrowse", titleKey: "home.toolGbrowseLabel", descriptionKey: "home.toolGbrowseDescription" },
  { to: "/blast", testId: "task-blast", titleKey: "home.toolBlastLabel", descriptionKey: "home.toolBlastDescription" },
  { to: "/search/primer", testId: "task-primer", titleKey: "home.toolPrimerLabel", descriptionKey: "home.toolPrimerDescription" },
] as const;

const isAssembliesPending = computed(() => toValue(assembliesQuery.isPending));
const isAssembliesError = computed(() => toValue(assembliesQuery.isError));
const isNewsPending = computed(() => toValue(newsQuery.isPending));
const isNewsError = computed(() => toValue(newsQuery.isError));

function submitSearch() {
  const value = query.value.trim();
  if (!value) return;
  void router.push({
    path: "/search",
    query: {
      q: value,
      ...(site.assemblyKey ? { assembly: site.assemblyKey } : {}),
    },
  });
}

function selectAssembly(assembly: AssemblyInfo) {
  // Assembly IDs, not display names, distinguish versions such as Wm82 v4/v5.
  site.setAssembly(String(assembly.id));
}

function newsTitle(item: NewsSummary): string {
  if (currentLanguage.value === "zh" && !item.title_zh) {
    return `${item.title_en} ${t("news.fallbackEnglishTitle")}`;
  }
  return currentLanguage.value === "zh" ? item.title_zh! : item.title_en;
}

function newsDate(item: NewsSummary): string {
  const value = item.published_at ?? item.created_at;
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(currentLanguage.value, { dateStyle: "medium" }).format(date);
}
</script>

<template>
  <PortalLayout>
    <div class="bg-background text-foreground">
      <section class="border-b border-border/80">
        <div class="mx-auto max-w-6xl px-4 py-14 text-center sm:py-16 lg:py-20">
          <h1 class="text-3xl font-semibold tracking-tight sm:text-4xl lg:text-5xl">
            {{ t("home.heroTitle") }}
          </h1>
          <p class="mx-auto mt-4 max-w-2xl text-base leading-7 text-muted-foreground sm:text-lg">
            {{ t("home.heroSubtitle") }}
          </p>

          <form
            class="mx-auto mt-8 flex w-full max-w-3xl flex-col gap-3 sm:flex-row"
            role="search"
            @submit.prevent="submitSearch"
          >
            <label class="sr-only" for="home-search">{{ t("search.title") }}</label>
            <input
              id="home-search"
              v-model="query"
              type="search"
              class="min-h-12 min-w-0 flex-1 rounded-lg border border-border bg-card px-4 text-base shadow-sm outline-none transition focus-visible:ring-2 focus-visible:ring-ring"
              :placeholder="t('home.searchPlaceholder')"
              data-testid="home-search-input"
            />
            <Button
              html-type="submit"
              size="large"
              type="primary"
              :disabled="!query.trim()"
              class="min-h-12 sm:min-w-32"
              data-testid="home-search-submit"
            >
              {{ t("common.search") }}
            </Button>
          </form>

          <p class="mt-4 text-sm text-muted-foreground" data-testid="home-context">
            {{ site.siteVariant }} · {{ t("releases.title") }}:
            {{ site.releaseId ?? t("releases.active") }}
            <span v-if="selectedAssembly"> · {{ t("home.selectedAssembly") }}: {{ selectedAssembly.name }} {{ selectedAssembly.version }}</span>
          </p>
        </div>
      </section>

      <section class="border-b border-border/80 bg-muted/40" aria-labelledby="database-entrypoints-heading" data-testid="database-entrypoints">
        <div class="mx-auto max-w-6xl px-4 py-10 sm:py-12">
          <div class="mb-6 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 id="database-entrypoints-heading" class="text-2xl font-semibold tracking-tight">
                {{ t("home.databaseTitle") }}
              </h2>
              <p class="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                {{ t("home.databaseSubtitle") }}
              </p>
            </div>
            <RouterLink
              to="/search"
              class="rounded-md px-3 py-2 text-sm font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="home-open-search"
            >
              {{ t("home.databaseSearch") }} →
            </RouterLink>
          </div>

          <ul class="grid gap-4 md:grid-cols-3" data-testid="database-entry-list">
            <li v-for="entry in DATABASE_ENTRIES" :key="entry.key">
              <RouterLink
                :to="entry.to"
                class="group flex h-full min-h-32 flex-col rounded-xl border border-border bg-card p-5 shadow-sm outline-none transition duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring"
                :data-testid="`database-${entry.key}`"
              >
                <span class="text-lg font-semibold text-foreground group-hover:text-primary">
                  {{ t(entry.titleKey) }}
                </span>
                <span class="mt-2 text-sm leading-6 text-muted-foreground">
                  {{ t(entry.descriptionKey) }}
                </span>
              </RouterLink>
            </li>
          </ul>
        </div>
      </section>

      <div class="mx-auto grid max-w-6xl gap-10 px-4 py-10 lg:grid-cols-[1.15fr_0.85fr] lg:py-12">
        <section aria-labelledby="task-entries-heading">
          <div class="mb-5">
            <h2 id="task-entries-heading" class="text-xl font-semibold tracking-tight">
              {{ t("home.tasks") }}
            </h2>
            <p class="mt-1 text-sm text-muted-foreground">{{ t("home.tasksSubtitle") }}</p>
          </div>
          <ul class="grid gap-3 sm:grid-cols-2" data-testid="task-entries">
            <li v-for="entry in TASK_ENTRIES" :key="entry.to">
              <RouterLink
                :to="entry.to"
                class="flex min-h-24 flex-col justify-center rounded-lg border border-border bg-card px-4 py-3 outline-none transition-colors hover:border-primary/50 hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
                :data-testid="entry.testId"
              >
                <span class="font-medium">{{ t(entry.titleKey) }}</span>
                <span class="mt-1 text-sm text-muted-foreground">{{ t(entry.descriptionKey) }}</span>
              </RouterLink>
            </li>
          </ul>
        </section>

        <section aria-labelledby="assemblies-heading" data-testid="assemblies-section">
          <div class="mb-5">
            <h2 id="assemblies-heading" class="text-xl font-semibold tracking-tight">
              {{ t("home.assemblies") }}
            </h2>
            <p class="mt-1 text-sm text-muted-foreground">{{ t("home.assembliesSubtitle") }}</p>
          </div>

          <p v-if="isAssembliesPending" role="status" data-testid="assemblies-loading" class="min-h-10 py-2 text-sm text-muted-foreground">
            {{ t("common.loading") }}
          </p>
          <div v-else-if="isAssembliesError" class="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-800" data-testid="assemblies-error" role="alert">
            <p>{{ t("home.assembliesUnavailable") }}</p>
            <Button size="small" class="mt-2" @click="assembliesQuery.refetch()">{{ t("common.retry") }}</Button>
          </div>
          <p v-else-if="assemblies.length === 0" data-testid="assemblies-empty" class="rounded-lg border border-border p-4 text-sm text-muted-foreground">
            {{ t("common.noData") }}
          </p>
          <ul v-else class="divide-y divide-border rounded-xl border border-border bg-card" data-testid="assemblies-list">
            <li v-for="assembly in assemblies" :key="String(assembly.id)" class="flex min-h-16 items-center justify-between gap-3 px-4 py-3">
              <div class="min-w-0">
                <p class="font-medium">{{ assembly.name }} <span class="font-normal text-muted-foreground">{{ assembly.version }}</span></p>
                <p class="mt-0.5 truncate text-xs text-muted-foreground">{{ assembly.species }}</p>
              </div>
              <Button
                size="small"
                :type="site.assemblyKey === String(assembly.id) ? 'primary' : 'default'"
                :aria-pressed="site.assemblyKey === String(assembly.id)"
                :data-testid="`assembly-select-${assembly.id}`"
                @click="selectAssembly(assembly)"
              >
                {{ site.assemblyKey === String(assembly.id) ? t("home.selected") : t("home.selectAssembly") }}
              </Button>
              <Tag v-if="assembly.is_default" color="green">{{ t("home.defaultAssembly") }}</Tag>
            </li>
          </ul>
        </section>
      </div>

      <section class="border-t border-border/80 bg-muted/30" aria-labelledby="latest-news-heading" data-testid="home-news-section">
        <div class="mx-auto max-w-6xl px-4 py-10 sm:py-12">
          <div class="mb-5 flex items-end justify-between gap-4">
            <div>
              <h2 id="latest-news-heading" class="text-xl font-semibold tracking-tight">
                {{ t("nav.latestNews") }}
              </h2>
              <p class="mt-1 text-sm text-muted-foreground">{{ t("home.newsSubtitle") }}</p>
            </div>
            <RouterLink to="/news" class="text-sm font-medium text-primary hover:underline" data-testid="home-all-news">
              {{ t("news.viewAll") }} →
            </RouterLink>
          </div>

          <p v-if="isNewsPending" role="status" aria-live="polite" data-testid="home-news-loading" class="rounded-lg border border-border bg-card p-5 text-sm text-muted-foreground">
            {{ t("common.loading") }}
          </p>
          <div v-else-if="isNewsError" role="alert" data-testid="home-news-error" class="rounded-lg border border-red-300 bg-card p-5">
            <p class="font-medium text-red-800">{{ t("news.homeUnavailable") }}</p>
            <p class="mt-1 text-sm text-muted-foreground">{{ t("news.loadErrorSubtitle") }}</p>
            <Button size="small" class="mt-3" @click="newsQuery.refetch()">{{ t("common.retry") }}</Button>
          </div>
          <p v-else-if="news.length === 0" data-testid="home-news-empty" class="rounded-lg border border-border bg-card p-5 text-sm text-muted-foreground">
            {{ t("home.noNews") }}
          </p>
          <ul v-else class="divide-y divide-border rounded-xl border border-border bg-card" data-testid="home-news-list">
            <li v-for="item in news" :key="item.slug" class="px-4 py-3 sm:px-5">
              <RouterLink :to="{ path: `/news/${item.slug}`, query: currentLanguage === 'zh' ? { lang: 'zh' } : {} }" class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded-sm font-medium outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-ring" :data-testid="`home-news-${item.slug}`">
                <span>{{ newsTitle(item) }}</span>
                <time class="shrink-0 text-xs font-normal text-muted-foreground">{{ newsDate(item) }}</time>
              </RouterLink>
            </li>
          </ul>
        </div>
      </section>
    </div>
  </PortalLayout>
</template>
