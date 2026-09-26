<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";
import { useRoute, useRouter } from "vue-router";

import type { NewsSummary } from "@soymutdb/api-client";
import { ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { newsListQueryOptions } from "../lib/query-options";
import { t } from "../lib/i18n";

// Public news list (Phase 3 parity). The filters live in the URL
// (/news?category=update&page=2) so reload, back/forward, and shared links
// reproduce the same view; the locale is a query parameter too (?lang=zh) and
// is never inferred from the host or a cookie.
const PAGE_SIZE = 10;
const CATEGORIES = ["all", "news", "update", "announcement"] as const;

/** Category buttons show dictionary labels, not the raw query values. */
function categoryLabel(value: string): string {
  const keys: Record<string, string> = {
    all: "news.categories.all",
    news: "news.categories.news",
    update: "news.categories.update",
    announcement: "news.categories.announcement",
  };
  return t(keys[value] ?? "news.categories.all");
}

const route = useRoute();
const router = useRouter();

const category = computed(() => {
  const raw = route.query.category ? String(route.query.category) : "all";
  return (CATEGORIES as readonly string[]).includes(raw) ? raw : "all";
});
const page = computed(() => {
  const raw = Number(route.query.page);
  return Number.isInteger(raw) && raw >= 1 ? raw : 1;
});
const lang = computed(() => (route.query.lang === "zh" ? "zh" : "en"));

const query = useQuery(
  computed(() =>
    newsListQueryOptions({
      category: category.value === "all" ? undefined : category.value,
      page: page.value,
      pageSize: PAGE_SIZE,
    }),
  ),
);

const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const response = computed(() => toValue(query.data));
const items = computed<NewsSummary[]>(() => response.value?.items ?? []);
const total = computed(() => response.value?.total ?? 0);
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)));

function displayTitle(item: NewsSummary): string {
  return lang.value === "zh" ? item.title_zh || item.title_en : item.title_en;
}

function publishedOn(item: NewsSummary): string {
  const value = item.published_at ?? item.created_at;
  return value ? value.slice(0, 10) : "—";
}

function queryFor(nextCategory: string, nextPage: number): Record<string, string> {
  const result: Record<string, string> = {};
  if (nextCategory !== "all") result.category = nextCategory;
  if (nextPage > 1) result.page = String(nextPage);
  if (lang.value === "zh") result.lang = "zh";
  return result;
}

function selectCategory(next: string) {
  void router.replace({ path: "/news", query: queryFor(next, 1) });
}

function goToPage(next: number) {
  const clamped = Math.min(Math.max(next, 1), totalPages.value);
  void router.replace({ path: "/news", query: queryFor(category.value, clamped) });
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="mx-auto max-w-3xl p-8">
      <p class="text-sm opacity-70"><RouterLink to="/" class="underline">{{ t("nav.home") }}</RouterLink></p>
      <h1 class="mt-2 text-2xl font-semibold">{{ t("news.title") }}</h1>
      <p class="mt-2 text-sm opacity-70">
        {{ t("news.subtitle") }}
      </p>

      <nav class="mt-6 flex flex-wrap gap-2" :aria-label="t('news.categoriesAria')">
        <button
          v-for="option in CATEGORIES"
          :key="option"
          type="button"
          class="rounded-md border px-3 py-1 text-sm capitalize"
          :class="{ 'border-primary font-medium': category === option }"
          :aria-pressed="category === option"
          :data-testid="`news-category-${option}`"
          @click="selectCategory(option)"
        >
          {{ categoryLabel(option) }}
        </button>
      </nav>

      <div v-if="isLoading" data-testid="news-loading" class="mt-6 grid gap-3">
        <div v-for="index in 3" :key="index" class="h-16 w-full rounded bg-black/5" />
      </div>
      <div v-else-if="isError" data-testid="news-error" class="mt-6 rounded border border-red-300 p-5">
        <p class="font-medium">{{ t("news.loadErrorTitle") }}</p>
      </div>

      <section v-else data-testid="news-results" class="mt-6" :aria-label="t('news.articlesAria')">
        <p class="mb-3 text-sm opacity-70" data-testid="news-total">
          {{ t("news.total", { count: total }) }}
        </p>
        <p v-if="items.length === 0" data-testid="news-empty" class="text-sm opacity-70">
          {{ t("news.emptyCategory") }}
        </p>
        <ul v-else class="grid gap-3">
          <li v-for="item in items" :key="item.id">
            <RouterLink
              :to="{ path: `/news/${item.slug}`, query: lang === 'zh' ? { lang: 'zh' } : {} }"
              data-testid="news-row"
              class="flex items-center gap-3 rounded-lg border p-4 transition-colors hover:border-primary"
            >
              <Tag v-if="item.category" class="font-mono uppercase">{{ item.category }}</Tag>
              <span class="min-w-0 flex-1 truncate font-medium">{{ displayTitle(item) }}</span>
              <time class="shrink-0 text-xs opacity-60">{{ publishedOn(item) }}</time>
            </RouterLink>
          </li>
        </ul>

        <nav
          v-if="totalPages > 1"
          class="mt-4 flex items-center justify-between text-sm"
          :aria-label="t('news.paginationAria')"
        >
          <button
            type="button"
            class="rounded-md border px-3 py-1 disabled:opacity-50"
            :disabled="page <= 1"
            data-testid="news-previous"
            @click="goToPage(page - 1)"
          >
            {{ t("news.prevPage") }}
          </button>
          <span class="opacity-70" data-testid="news-page">{{ t("news.pageOf", { page, pages: totalPages }) }}</span>
          <button
            type="button"
            class="rounded-md border px-3 py-1 disabled:opacity-50"
            :disabled="page >= totalPages"
            data-testid="news-next"
            @click="goToPage(page + 1)"
          >
            {{ t("news.nextPage") }}
          </button>
        </nav>
      </section>
    </div>
  </ConfigProvider>
</template>
