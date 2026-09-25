<script setup lang="ts">
import DOMPurify from "dompurify";
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";
import { useRoute } from "vue-router";

import { ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { newsDetailQueryOptions } from "../lib/query-options";

// Public news article (Phase 3 parity). The article body is CMS HTML: the
// backend sanitises it, and the client re-sanitises with DOMPurify before
// v-html (defence in depth, mirroring the React route). The locale is a query
// parameter (?lang=zh) so a shared link keeps the reader's language.
const route = useRoute();
const slug = computed(() => String(route.params.slug));
const lang = computed(() => (route.query.lang === "zh" ? "zh" : "en"));

const query = useQuery(computed(() => newsDetailQueryOptions({ slug: slug.value })));

const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const article = computed(() => toValue(query.data));

const title = computed(() => {
  const current = article.value;
  if (!current) return "";
  return lang.value === "zh" ? current.title_zh || current.title_en : current.title_en;
});

const body = computed(() => {
  const current = article.value;
  if (!current) return "";
  const html =
    lang.value === "zh" && current.content_zh ? current.content_zh : current.content_en;
  return DOMPurify.sanitize(html);
});

const publishedOn = computed(() => article.value?.published_at?.slice(0, 10) ?? "—");

const listQuery = computed(() => (lang.value === "zh" ? { lang: "zh" } : {}));
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="mx-auto max-w-3xl p-8">
      <p class="text-sm opacity-70">
        <RouterLink :to="{ path: '/news', query: listQuery }" class="underline">
          News
        </RouterLink>
      </p>

      <div v-if="isLoading" data-testid="news-detail-loading" class="mt-6 h-24 animate-pulse rounded bg-black/5" />

      <div v-else-if="isError" data-testid="news-detail-error" class="mt-6 rounded border border-red-300 p-5">
        <p class="font-medium">This article is unavailable.</p>
      </div>

      <article v-else-if="article" data-testid="news-detail" class="mt-4">
        <div class="flex items-center gap-2">
          <Tag v-if="article.category" class="font-mono uppercase">{{ article.category }}</Tag>
          <time class="text-xs opacity-60" data-testid="news-detail-date">{{ publishedOn }}</time>
        </div>
        <h1 class="mt-2 text-2xl font-semibold" data-testid="news-detail-title">{{ title }}</h1>

        <!-- Sanitised CMS HTML; see the setup comment for the trust boundary. -->
        <div class="prose mt-6 text-sm" data-testid="news-detail-body" v-html="body" />
      </article>

      <div v-else data-testid="news-detail-empty" class="mt-6 text-sm opacity-70">
        Article not found.
      </div>
    </div>
  </ConfigProvider>
</template>
