<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, onMounted, onUnmounted, ref, toValue } from "vue";
import { useRouter } from "vue-router";

import type { AssemblyInfo, NewsSummary } from "@soymutdb/api-client";
import { Button, Card, Tag } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import ResourceCardsNode from "../components/home/ResourceCardsNode.vue";
import FluidGradient from "../components/visuals/FluidGradient.vue";
import IconGlyph from "../components/visuals/IconGlyph.vue";
import { HERO_PALETTES } from "../components/visuals/fluid-palettes";
import { isJbrowseEnabled } from "../lib/deployment";
import { currentLanguage, t } from "../lib/i18n";
import { isSafePageHref, usePageDefinition } from "../lib/page-definition";
import { assembliesQueryOptions, featuredNewsQueryOptions } from "../lib/query-options";
import { useSiteContent } from "../lib/site-content";
import { useSiteContextStore } from "../stores/site-context";

const site = useSiteContextStore();
const { get } = useSiteContent();
// The 资源导览 band is the one block the page builder owns for "/". When the
// API has no published node the built-in band below renders unchanged.
const { resourceCards } = usePageDefinition("/");
// React parity: the home hero accepts an operator-set image. The stored value is
// untrusted input, so only absolute http(s) or site-relative targets render —
// `isSafePageHref` already rejects `javascript:`/`data:`/protocol-relative and
// backslashes; `mailto:`/`tel:` make no sense for an <img> and are excluded too.
const heroImage = computed(() => {
  const value = get("hero.image", "");
  if (!isSafePageHref(value) || /^(mailto:|tel:)/i.test(value)) return "";
  return value;
});
const router = useRouter();
const query = ref("");
const searchHint = ref("");

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
    icon: "gene",
    titleKey: "home.database.genes",
    descriptionKey: "home.database.genesDescription",
  },
  {
    key: "variants",
    to: "/variants",
    icon: "variant",
    titleKey: "home.database.variants",
    descriptionKey: "home.database.variantsDescription",
  },
  {
    key: "mutants",
    to: "/mutants",
    icon: "mutant",
    titleKey: "home.database.mutants",
    descriptionKey: "home.database.mutantsDescription",
  },
] as const;

// React order (antd-home.tsx TOOL_ENTRIES): gene / location / gbrowse /
// primer / blast. The `*ContentKey` is the backend-editable override; the
// `*Key` stays the locale-aware i18n fallback when no override is stored.
const TASK_ENTRIES = [
  { to: "/search/genes", testId: "task-gene-search", icon: "idcard", labelContentKey: "tool.gene.label", titleKey: "home.toolGeneLabel", descriptionContentKey: "tool.gene.desc", descriptionKey: "home.toolGeneDescription" },
  { to: "/search/location", testId: "task-location-search", icon: "environment", labelContentKey: "tool.location.label", titleKey: "home.toolLocationLabel", descriptionContentKey: "tool.location.desc", descriptionKey: "home.toolLocationDescription" },
  { to: "/search/gbrowse", testId: "task-jbrowse", icon: "global", labelContentKey: "tool.gbrowse.label", titleKey: "home.toolGbrowseLabel", descriptionContentKey: "tool.gbrowse.desc", descriptionKey: "home.toolGbrowseDescription" },
  { to: "/search/primer", testId: "task-primer", icon: "experiment", labelContentKey: "tool.primer.label", titleKey: "home.toolPrimerLabel", descriptionContentKey: "tool.primer.desc", descriptionKey: "home.toolPrimerDescription" },
  { to: "/blast", testId: "task-blast", icon: "thunderbolt", labelContentKey: "tool.blast.label", titleKey: "home.toolBlastLabel", descriptionContentKey: "tool.blast.desc", descriptionKey: "home.toolBlastDescription" },
] as const;

const RESOURCE_ENTRIES = [
  { to: "/downloads", icon: "download", titleKey: "home.resourceDownloads", descriptionKey: "home.resourceDownloadsDesc" },
  { to: "/guide", icon: "guide", titleKey: "home.resourceGuide", descriptionKey: "home.resourceGuideDesc" },
  { to: "/publications", icon: "publications", titleKey: "home.resourcePublications", descriptionKey: "home.resourcePublicationsDesc" },
] as const;

// Hero carousel slides: the first reuses the page hero copy, the others carry
// the React `home.heroSlide2/3` copy.
const HERO_SLIDES = [
  { titleKey: "home.heroTitle", subtitleKey: "home.heroSubtitle" },
  { titleKey: "home.heroSlide2", subtitleKey: "home.heroSlide2Desc" },
  { titleKey: "home.heroSlide3", subtitleKey: "home.heroSlide3Desc" },
] as const;

const slideIndex = ref(0);
let autoplay: ReturnType<typeof setInterval> | undefined;

const isAssembliesPending = computed(() => toValue(assembliesQuery.isPending));
const isAssembliesError = computed(() => toValue(assembliesQuery.isError));
const isNewsPending = computed(() => toValue(newsQuery.isPending));
const isNewsError = computed(() => toValue(newsQuery.isError));

// A core-only deployment runs no genome browser: its entry card would link into
// a route that only explains the feature is absent.
const taskEntries = computed(() =>
  isJbrowseEnabled()
    ? TASK_ENTRIES
    : TASK_ENTRIES.filter((entry) => entry.testId !== "task-jbrowse"),
);

function submitSearch() {
  const value = query.value.trim();
  if (!value) {
    // The React hero button stays clickable and only validates on submit.
    searchHint.value = t("home.searchEmptyHint");
    return;
  }
  searchHint.value = "";
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

onMounted(() => {
  const reduced =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduced) {
    autoplay = setInterval(() => {
      slideIndex.value = (slideIndex.value + 1) % HERO_SLIDES.length;
    }, 5200);
  }
});

onUnmounted(() => {
  if (autoplay) clearInterval(autoplay);
});
</script>

<template>
  <PortalLayout>
    <div class="bg-background text-foreground">
      <!-- 1. Full-width fluid-gradient hero -->
      <FluidGradient
        :colors="HERO_PALETTES[0]"
        class="home-hero"
        data-testid="home-hero"
      >
        <div class="container-prose py-16 md:py-24">
          <div class="max-w-3xl">
            <p
              class="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/70"
              data-testid="home-hero-eyebrow"
            >
              {{ get("hero.eyebrow", t("home.heroEyebrow")) }}
            </p>
            <h1
              class="font-display mt-5 text-4xl font-bold leading-[1.1] tracking-tight text-white md:text-5xl lg:text-6xl"
              style="text-shadow: 0 2px 20px rgba(0, 0, 0, 0.3)"
            >
              {{ get("hero.title", t("home.heroTitle")) }}
            </h1>
            <p class="mt-5 max-w-2xl text-base leading-7 text-white/80 md:text-lg">
              {{ get("hero.subtitle", t("home.heroSubtitle")) }}
            </p>

            <form
              class="mt-8 flex w-full max-w-2xl flex-wrap items-center gap-3"
              role="search"
              @submit.prevent="submitSearch"
            >
              <label class="sr-only" for="home-search">{{ t("search.title") }}</label>
              <div class="home-hero-search relative flex min-w-[14rem] flex-1 items-center">
                <IconGlyph name="search" class="pointer-events-none absolute left-4 text-base text-muted-foreground" />
                <input
                  id="home-search"
                  v-model="query"
                  type="search"
                  class="min-h-12 w-full rounded-full border border-white/40 bg-white/95 pl-11 pr-4 text-base text-foreground shadow-lg outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-white/80"
                  :placeholder="get('hero.searchPlaceholder', t('home.searchPlaceholder'))"
                  data-testid="home-search-input"
                  @input="searchHint = ''"
                />
              </div>
              <Button
                html-type="submit"
                size="large"
                type="primary"
                class="min-h-12 rounded-full px-7"
                data-testid="home-search-submit"
              >
                {{ t("common.search") }}
              </Button>
            </form>

            <p v-if="searchHint" class="mt-3 text-sm font-medium text-white" data-testid="home-search-hint">
              {{ searchHint }}
            </p>
            <p class="mt-3 text-sm text-white/70" data-testid="home-search-examples">
              {{ t("home.searchExamples") }}
            </p>

            <div class="mt-7 flex flex-wrap gap-3">
              <Button
                type="primary"
                size="large"
                class="home-hero-cta min-h-12 rounded-full px-7"
                data-testid="home-hero-primary"
                @click="router.push('/search')"
              >
                {{ t("home.heroPrimary") }}
                <IconGlyph name="arrow-right" class="ms-2 text-sm" />
              </Button>
              <button
                type="button"
                class="min-h-12 rounded-full border border-white/60 px-7 text-base font-medium text-white outline-none transition-colors hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-white/80"
                data-testid="home-hero-secondary"
                @click="router.push('/about')"
              >
                {{ t("home.heroSecondary") }}
              </button>
            </div>

            <!-- Operator-set hero image (React parity: `get("hero.image","")`).
                 Rendered only for an absolute http(s) or site-relative URL; the
                 value is operator input, so script-like and protocol-relative
                 targets are dropped rather than trusted. -->
            <div
              v-if="heroImage"
              class="mt-10 aspect-[16/9] w-full max-w-3xl overflow-hidden rounded-2xl border border-white/30 shadow-lg"
              data-testid="home-hero-image"
            >
              <img
                :src="heroImage"
                :alt="get('hero.title', t('home.heroTitle'))"
                loading="lazy"
                class="h-full w-full object-cover"
              />
            </div>

            <p class="mt-6 text-sm text-white/70" data-testid="home-context">
              {{ site.siteVariant }} · {{ t("releases.title") }}:
              {{ site.releaseId ?? t("releases.active") }}
              <span v-if="selectedAssembly"> · {{ t("home.selectedAssembly") }}: {{ selectedAssembly.name }} {{ selectedAssembly.version }}</span>
            </p>
          </div>
        </div>
      </FluidGradient>

      <!-- 2. Database entry points (AGENTS.md: must stay ahead of marketing) -->
      <section class="border-b border-border/80 bg-muted/40" aria-labelledby="database-entrypoints-heading" data-testid="database-entrypoints">
        <div class="mx-auto max-w-6xl px-4 py-10 sm:py-12">
          <div class="mb-6 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p class="eyebrow">{{ t("home.databaseEyebrow") }}</p>
              <h2 id="database-entrypoints-heading" class="mt-2 text-2xl font-semibold tracking-tight">
                {{ t("home.databaseTitle") }}
              </h2>
              <p class="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                {{ t("home.databaseSubtitle") }}
              </p>
            </div>
            <RouterLink
              to="/search"
              class="home-section-link rounded-md text-sm font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
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
                <span class="flex size-11 items-center justify-center rounded-lg bg-accent text-xl text-accent-foreground">
                  <IconGlyph :name="entry.icon" />
                </span>
                <span class="mt-4 text-lg font-semibold text-foreground group-hover:text-primary">
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

      <!-- 3. Latest news (left) ‖ fluid-gradient slide carousel (right) -->
      <div class="mx-auto grid max-w-6xl gap-8 px-4 py-12 lg:grid-cols-[2fr_3fr]">
        <section class="flex flex-col" aria-labelledby="latest-news-heading" data-testid="home-news-section">
          <div class="mb-4 flex items-baseline justify-between gap-3">
            <h2 id="latest-news-heading" class="text-xl font-semibold tracking-tight">
              {{ t("nav.latestNews") }}
            </h2>
            <RouterLink to="/news" class="home-section-link text-sm font-medium text-primary hover:underline" data-testid="home-all-news">
              {{ t("home.openTool") }} →
            </RouterLink>
          </div>

          <Card class="home-news-card flex-1 rounded-xl border border-border bg-card shadow-sm">
            <p v-if="isNewsPending" role="status" aria-live="polite" data-testid="home-news-loading" class="px-4 py-4 text-sm text-muted-foreground">
              {{ t("common.loading") }}
            </p>
            <div v-else-if="isNewsError" role="alert" data-testid="home-news-error" class="m-4 rounded-lg border border-red-300 bg-red-50 p-4">
              <p class="font-medium text-red-800">{{ t("home.newsUnavailable") }}</p>
              <p class="mt-1 text-sm text-red-700/80">{{ t("home.newsRetry") }}</p>
              <Button size="small" class="mt-3" @click="newsQuery.refetch()">{{ t("common.retry") }}</Button>
            </div>
            <p v-else-if="news.length === 0" data-testid="home-news-empty" class="px-4 py-4 text-sm text-muted-foreground">
              {{ t("home.noNews") }}
            </p>
            <ul v-else data-testid="home-news-list">
              <li v-for="item in news" :key="item.slug" class="border-b border-border/70 px-4 last:border-b-0">
                <RouterLink
                  :to="{ path: `/news/${item.slug}`, query: currentLanguage === 'zh' ? { lang: 'zh' } : {} }"
                  class="home-news-link block border-l-2 border-transparent py-3 pl-3 outline-none transition-colors hover:border-primary hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
                  :data-testid="`home-news-${item.slug}`"
                >
                  <span class="block font-medium">{{ newsTitle(item) }}</span>
                  <span class="mt-1 block text-xs text-muted-foreground">
                    {{ item.category ? `${item.category} · ` : "" }}{{ newsDate(item) }}
                  </span>
                </RouterLink>
              </li>
            </ul>
          </Card>
        </section>

        <section class="flex flex-col" aria-labelledby="hero-carousel-heading" data-testid="home-carousel">
          <h2 id="hero-carousel-heading" class="sr-only">{{ t("home.featuredTools") }}</h2>
          <FluidGradient
            v-for="(slide, index) in HERO_SLIDES"
            v-show="slideIndex === index"
            :key="slide.titleKey"
            :colors="HERO_PALETTES[index % HERO_PALETTES.length]"
            class="min-h-[22rem] flex-1 rounded-xl"
          >
            <div class="flex h-full flex-col p-8 md:p-12">
              <p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-white/70">
                {{ t("home.heroEyebrow") }}
              </p>
              <h3 class="font-display mt-4 text-2xl font-bold leading-tight text-white md:text-3xl" style="text-shadow: 0 2px 20px rgba(0, 0, 0, 0.3)">
                {{ t(slide.titleKey) }}
              </h3>
              <p class="mt-3 max-w-xl text-sm leading-7 text-white/85">
                {{ t(slide.subtitleKey) }}
              </p>
              <div class="mt-auto pt-6">
                <Button type="primary" @click="router.push('/search')">
                  {{ t("home.heroPrimary") }}
                  <IconGlyph name="arrow-right" class="ms-2 text-sm" />
                </Button>
              </div>
            </div>
          </FluidGradient>
          <div class="mt-4 flex justify-center gap-2" role="tablist" :aria-label="t('home.heroPrimary')">
            <button
              v-for="(slide, index) in HERO_SLIDES"
              :key="`dot-${slide.titleKey}`"
              type="button"
              role="tab"
              :aria-selected="slideIndex === index"
              :aria-label="`${index + 1}`"
              class="size-2.5 rounded-full outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring"
              :class="slideIndex === index ? 'bg-primary' : 'bg-border hover:bg-muted-foreground/60'"
              :data-testid="`home-carousel-dot-${index}`"
              @click="slideIndex = index"
            />
          </div>
        </section>
      </div>

      <!-- 4. Research tools -->
      <section class="border-t border-border/80 bg-muted/20" aria-labelledby="task-entries-heading">
        <div class="mx-auto max-w-6xl px-4 py-12">
          <div class="mb-5 flex items-baseline justify-between gap-3">
            <div>
              <h2 id="task-entries-heading" class="text-xl font-semibold tracking-tight">
                {{ t("home.featuredTools") }}
              </h2>
              <p class="mt-1 text-sm text-muted-foreground">{{ t("home.tasksSubtitle") }}</p>
            </div>
            <RouterLink to="/search" class="home-section-link text-sm font-medium text-primary hover:underline">
              {{ t("home.openTool") }} →
            </RouterLink>
          </div>
          <ul class="grid gap-4 sm:grid-cols-2 lg:grid-cols-5" data-testid="task-entries">
            <li v-for="entry in taskEntries" :key="entry.to">
              <RouterLink
                :to="entry.to"
                class="group flex h-full min-h-32 flex-col rounded-xl border border-border bg-card p-4 shadow-sm outline-none transition duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring"
                :data-testid="entry.testId"
              >
                <span class="flex size-11 items-center justify-center rounded-lg bg-accent text-xl text-accent-foreground">
                  <IconGlyph :name="entry.icon" />
                </span>
                <span class="mt-3 font-semibold text-foreground group-hover:text-primary">{{ get(entry.labelContentKey, t(entry.titleKey)) }}</span>
                <span class="mt-1 text-sm leading-6 text-muted-foreground">{{ get(entry.descriptionContentKey, t(entry.descriptionKey)) }}</span>
              </RouterLink>
            </li>
          </ul>
        </div>
      </section>

      <!-- 5. Genome assemblies -->
      <section class="border-t border-border/80" aria-labelledby="assemblies-heading" data-testid="assemblies-section">
        <div class="mx-auto max-w-6xl px-4 py-12">
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
          <ul v-else class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="assemblies-list">
            <li
              v-for="assembly in assemblies"
              :key="String(assembly.id)"
              class="flex min-h-16 items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-sm"
            >
              <div class="min-w-0">
                <p class="font-medium">{{ assembly.name }} <span class="font-normal text-muted-foreground">{{ assembly.version }}</span></p>
                <p class="mt-0.5 truncate text-xs text-muted-foreground">{{ assembly.species }}</p>
              </div>
              <Tag v-if="assembly.is_default" color="green">{{ t("home.defaultAssembly") }}</Tag>
              <Button
                size="small"
                :type="site.assemblyKey === String(assembly.id) ? 'primary' : 'default'"
                :aria-pressed="site.assemblyKey === String(assembly.id)"
                :data-testid="`assembly-select-${assembly.id}`"
                @click="selectAssembly(assembly)"
              >
                {{ site.assemblyKey === String(assembly.id) ? t("home.selected") : t("home.selectAssembly") }}
              </Button>
            </li>
          </ul>
        </div>
      </section>

      <!-- 6. Resource guide — CMS-owned when the page builder publishes a
           `resource_cards` node for "/", otherwise the built-in band. The
           built-in band is the product's own default (real routes, real
           labels), not demo data, so falling back to it is always honest. -->
      <section class="border-t border-border/80 bg-muted/20" aria-labelledby="resource-guide-heading" data-testid="resource-guide">
        <div class="mx-auto max-w-6xl px-4 py-12">
          <template v-if="resourceCards">
            <h2 id="resource-guide-heading" class="sr-only">{{ t("home.resourceNav") }}</h2>
            <ResourceCardsNode :node="resourceCards" />
          </template>
          <template v-else>
            <h2 id="resource-guide-heading" class="text-xl font-semibold tracking-tight">
              {{ t("home.resourceNav") }}
            </h2>
            <ul class="mt-5 grid gap-4 md:grid-cols-3">
              <li v-for="entry in RESOURCE_ENTRIES" :key="entry.to">
                <RouterLink
                  :to="entry.to"
                  class="group flex h-full flex-col rounded-xl border border-border bg-card p-5 shadow-sm outline-none transition duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span class="flex size-11 items-center justify-center rounded-lg bg-accent text-xl text-accent-foreground">
                    <IconGlyph :name="entry.icon" />
                  </span>
                  <span class="mt-4 font-semibold text-foreground group-hover:text-primary">{{ t(entry.titleKey) }}</span>
                  <span class="mt-1 text-sm leading-6 text-muted-foreground">{{ t(entry.descriptionKey) }}</span>
                </RouterLink>
              </li>
            </ul>
          </template>
        </div>
      </section>
    </div>
  </PortalLayout>
</template>
