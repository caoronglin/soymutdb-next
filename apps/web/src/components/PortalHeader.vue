<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { cn } from "@soymutdb/shared/cn";
import { Button, ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { currentLanguage, setLanguage, t } from "../lib/i18n";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Portal chrome: brand, primary navigation, global search, and the deployment
 * context (site variant + pinned release).
 *
 * The site variant is never inferred from the host: it comes from the build
 * define validated at build time (DB-CORE-5), and the internal variant is
 * labelled so an operator never mistakes one artifact for the other.
 */
const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();

const query = ref("");
const menuOpen = ref(false);

const NAV = [
  { labelKey: "nav.explore", to: "/genes" },
  { labelKey: "nav.variants", to: "/variants" },
  { labelKey: "nav.mutantLines", to: "/mutants" },
  { labelKey: "nav.browser", to: "/browser" },
  { labelKey: "nav.blast", to: "/blast" },
  { labelKey: "nav.tools", to: "/tools" },
  { labelKey: "nav.analyses", to: "/analyses" },
  { labelKey: "nav.downloads", to: "/downloads" },
  { labelKey: "nav.resources", to: "/guide" },
  { labelKey: "nav.news", to: "/news" },
] as const;

const languageLabel = computed(() => (currentLanguage.value === "zh" ? "中文" : "EN"));
const nextLanguage = computed(() => (currentLanguage.value === "zh" ? "en" : "zh"));

function isActive(to: string): boolean {
  return route.path === to || (to !== "/" && route.path.startsWith(`${to}/`));
}

function submitSearch() {
  const value = query.value.trim();
  if (!value) return;
  menuOpen.value = false;
  void router.push({ path: "/search", query: { q: value } });
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <header class="sticky top-0 z-40 border-b bg-background/95 backdrop-blur">
      <div class="mx-auto flex h-16 max-w-7xl flex-wrap items-center gap-3 px-4">
        <RouterLink to="/" class="flex items-center gap-2 font-semibold" aria-label="SoyMutDB home">
          SoyMutDB
          <Tag v-if="site.isInternal" color="gold">Internal</Tag>
        </RouterLink>

        <nav class="hidden items-center gap-1 lg:flex" aria-label="Primary">
          <RouterLink
            v-for="item in NAV"
            :key="item.to"
            :to="item.to"
            :class="
              cn(
                'rounded-md px-2 py-1.5 text-sm',
                isActive(item.to) ? 'font-medium underline' : 'opacity-70 hover:opacity-100',
              )
            "
          >
            {{ t(item.labelKey) }}
          </RouterLink>
        </nav>

        <form class="ms-auto flex items-center gap-2" role="search" @submit.prevent="submitSearch">
          <label class="sr-only" for="portal-search">{{ t("nav.search") }}</label>
          <input
            id="portal-search"
            v-model="query"
            class="w-40 rounded-md border bg-background px-2 py-1 text-sm sm:w-56"
            :placeholder="t('search.placeholder')"
            data-testid="portal-search-input"
          />
          <Button size="small" html-type="submit" data-testid="portal-search-submit">
            {{ t("nav.search") }}
          </Button>
        </form>

        <Button size="small" @click="setLanguage(nextLanguage)">
          {{ languageLabel }}
        </Button>
        <Button class="lg:hidden" size="small" @click="menuOpen = !menuOpen">
          {{ menuOpen ? "×" : "≡" }}
        </Button>
      </div>

      <nav v-if="menuOpen" class="border-t px-4 py-2 lg:hidden" aria-label="Primary mobile">
        <RouterLink
          v-for="item in NAV"
          :key="item.to"
          :to="item.to"
          class="block py-1 text-sm"
          @click="menuOpen = false"
        >
          {{ t(item.labelKey) }}
        </RouterLink>
      </nav>

      <p class="border-t px-4 py-1 text-xs opacity-70" data-testid="portal-context">
        {{ t("releases.title") }}: {{ site.releaseId ?? t("releases.active") }} ·
        {{ site.siteVariant }}
      </p>
    </header>
  </ConfigProvider>
</template>
