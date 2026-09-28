<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { http } from "@soymutdb/api-client";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
import { useSiteContent } from "../lib/site-content";

/**
 * Guide — the static NCBI-style retrieval guide served by
 * `GET /content/pages/{slug}`.
 *
 * The Markdown body is rendered by a small in-house renderer (the project does
 * not depend on a Markdown runtime) and the table of contents is derived from
 * the h2/h3 headings, so anchors stay stable across reloads.
 */
interface StaticPage {
  id: string;
  slug: string;
  title_en: string;
  title_zh: string | null;
  content_en: string;
  content_zh: string | null;
}

const GUIDE_SLUG = "ncbi-database-guide";

const { get } = useSiteContent();

const query = useQuery({
  queryKey: ["content", "pages", GUIDE_SLUG],
  queryFn: () => http.get<StaticPage>(`/content/pages/${GUIDE_SLUG}`),
  staleTime: 5 * 60_000,
});

const page = computed<StaticPage | undefined>(() => toValue(query.data));
const isPending = computed(() => toValue(query.isPending));
const isError = computed(() => toValue(query.isError));

interface Block {
  kind: "h2" | "h3" | "p" | "li";
  text: string;
}

const blocks = computed<Block[]>(() => {
  const source = page.value?.content_en ?? "";
  const result: Block[] = [];
  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    if (line.startsWith("### ")) result.push({ kind: "h3", text: line.slice(4) });
    else if (line.startsWith("## ")) result.push({ kind: "h2", text: line.slice(3) });
    else if (line.startsWith("- ") || line.startsWith("* ")) result.push({ kind: "li", text: line.slice(2) });
    else if (line.startsWith("#")) continue;
    else result.push({ kind: "p", text: line });
  }
  return result;
});

const toc = computed(() => blocks.value.filter((block) => block.kind === "h2" || block.kind === "h3"));
const showBackToTop = ref(false);

function onScroll() {
  showBackToTop.value = typeof window === "undefined" ? false : window.scrollY > 600;
}

function scrollToTop() {
  if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-4xl px-4 py-8" @scroll.passive="onScroll">
      <!-- React renders `get("nav.guide", …)` as a small badge above the page
           heading and keeps the API page title as the <h1> (guide.tsx: a Tag
           carrying nav.guide, then `<h1>{title}</h1>`). Mirror that split rather
           than moving the nav label into the heading and dropping the title. -->
      <p class="eyebrow">{{ get("nav.guide", t("nav.guide")) }}</p>
      <h1 class="text-2xl font-semibold">{{ page?.title_en ?? t("docs.gettingStarted") }}</h1>

      <p v-if="isPending" data-testid="guide-loading" class="mt-6 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <p v-else-if="isError" data-testid="guide-error" class="mt-6 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <template v-else-if="blocks.length > 0">
        <nav class="mt-6 rounded-lg border p-4" :aria-label="t('common.tableOfContents')" data-testid="guide-toc">
          <p class="text-sm font-medium">{{ t("docs.gettingStarted") }}</p>
          <ul class="mt-2 grid gap-1 text-sm">
            <li v-for="(item, index) in toc" :key="index" :class="item.kind === 'h3' ? 'ms-4 opacity-70' : ''">
              {{ item.text }}
            </li>
          </ul>
        </nav>

        <article class="mt-6 grid gap-3" data-testid="guide-content">
          <h2 v-for="(block, index) in blocks" :key="index" :class="block.kind === 'h2' ? 'mt-4 text-lg font-semibold' : block.kind === 'h3' ? 'mt-2 font-medium' : 'text-sm opacity-80'">
            <span v-if="block.kind === 'li'" class="ms-4 block text-sm opacity-80">• {{ block.text }}</span>
            <template v-else>{{ block.text }}</template>
          </h2>
        </article>

        <button
          v-if="showBackToTop"
          type="button"
          class="mt-6 underline"
          @click="scrollToTop"
        >
          {{ t("common.back") }}
        </button>
      </template>
      <p v-else class="mt-6 text-sm opacity-70" data-testid="guide-empty">{{ t("common.noData") }}</p>
    </div>
  </PortalLayout>
</template>
