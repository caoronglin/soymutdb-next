<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { currentLanguage, setLanguage, t } from "../lib/i18n";
import { useSiteBranding } from "../lib/branding";
import { isJbrowseEnabled } from "../lib/deployment";
import { useSiteContextStore } from "../stores/site-context";

type NavigationChild = { kind: "link"; to: string; labelKey: string } | { kind: "separator" };
interface NavigationGroup {
  key: string;
  labelKey: string;
  to?: string;
  children?: NavigationChild[];
}

const NAV_GROUPS: readonly NavigationGroup[] = [
  {
    key: "explore",
    labelKey: "nav.explore",
    children: [
      { kind: "link", to: "/genes", labelKey: "nav.genes" },
      { kind: "link", to: "/variants", labelKey: "nav.variants" },
      { kind: "link", to: "/mutants", labelKey: "nav.mutantLines" },
      { kind: "link", to: "/browser", labelKey: "nav.browser" },
      { kind: "link", to: "/sra", labelKey: "nav.sra" },
      { kind: "link", to: "/compare", labelKey: "nav.compare" },
      { kind: "link", to: "/analytics", labelKey: "nav.analytics" },
    ],
  },
  {
    key: "tools",
    labelKey: "nav.tools",
    children: [
      { kind: "link", to: "/blast", labelKey: "nav.blast" },
      { kind: "link", to: "/analyses", labelKey: "nav.analyses" },
      { kind: "separator" },
      { kind: "link", to: "/tools/seqfetch", labelKey: "tools.seqfetch.title" },
      { kind: "link", to: "/tools/enrichment", labelKey: "tools.enrichment.title" },
      { kind: "link", to: "/tools/exppattern", labelKey: "tools.exppattern.title" },
      { kind: "separator" },
      { kind: "link", to: "/tools", labelKey: "nav.allTools" },
    ],
  },
  { key: "downloads", labelKey: "nav.downloads", to: "/downloads" },
  {
    key: "resources",
    labelKey: "nav.resources",
    children: [
      { kind: "link", to: "/guide", labelKey: "nav.guide" },
      { kind: "link", to: "/help", labelKey: "nav.help" },
      { kind: "link", to: "/news", labelKey: "nav.news" },
      { kind: "link", to: "/publications", labelKey: "nav.publications" },
      { kind: "link", to: "/seed-request", labelKey: "nav.seedRequest" },
      { kind: "link", to: "/about", labelKey: "nav.about" },
    ],
  },
];

// A core-only deployment does not run JBrowse: its nav entry is hidden rather
// than left as a link into a 502. The routes themselves are gated in
// router/index.ts so a deep link stays reachable and explains why.
const JBROWSE_ROUTES = ["/browser", "/gbrowse"] as const;
const disabledRoutes = new Set<string>(isJbrowseEnabled() ? [] : JBROWSE_ROUTES);
const navGroups = computed<readonly NavigationGroup[]>(() =>
  NAV_GROUPS.map((group) => ({
    ...group,
    children: group.children?.filter(
      (child) => child.kind !== "link" || !disabledRoutes.has(child.to),
    ),
  })),
);

const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();
const { displayName: siteName, iconUrl: siteIconUrl } = useSiteBranding();
const query = ref("");
const openGroup = ref<string | null>(null);
const mobileOpen = ref(false);
const navigationRef = ref<HTMLElement | null>(null);
const menuTrigger = ref<HTMLButtonElement | null>(null);
const mobileTrigger = ref<HTMLButtonElement | null>(null);

const languageButtonText = computed(() => (currentLanguage.value === "zh" ? "EN" : "中文"));
const nextLanguage = computed(() => (currentLanguage.value === "zh" ? "en" : "zh"));

function isActive(path: string): boolean {
  return route.path === path || (path !== "/" && route.path.startsWith(`${path}/`));
}

function isGroupActive(group: NavigationGroup): boolean {
  if (group.to) return isActive(group.to);
  return (group.children ?? []).some((child) => child.kind === "link" && isActive(child.to));
}

function toggleGroup(groupKey: string, event: MouseEvent) {
  const trigger = event.currentTarget;
  menuTrigger.value = trigger instanceof HTMLButtonElement ? trigger : null;
  openGroup.value = openGroup.value === groupKey ? null : groupKey;
}

function closeMobileMenu(restoreFocus = false) {
  mobileOpen.value = false;
  if (restoreFocus) void nextTick(() => mobileTrigger.value?.focus());
}

function closeMenusOnEscape(event: KeyboardEvent) {
  if (event.key !== "Escape") return;
  if (mobileOpen.value) {
    event.preventDefault();
    closeMobileMenu(true);
  } else if (openGroup.value) {
    event.preventDefault();
    openGroup.value = null;
    void nextTick(() => menuTrigger.value?.focus());
  }
}

function closeGroupOnOutsideClick(event: PointerEvent) {
  if (openGroup.value && navigationRef.value && !navigationRef.value.contains(event.target as Node)) {
    openGroup.value = null;
  }
}

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
  query.value = "";
  openGroup.value = null;
  closeMobileMenu();
}

watch(
  () => route.fullPath,
  () => {
    openGroup.value = null;
    closeMobileMenu();
  },
);

watch(mobileOpen, async (isOpen) => {
  if (!isOpen) return;
  await nextTick();
  document.querySelector<HTMLElement>("[data-testid='mobile-nav-first-link']")?.focus();
});

onMounted(() => {
  document.addEventListener("keydown", closeMenusOnEscape);
  document.addEventListener("pointerdown", closeGroupOnOutsideClick);
});

onUnmounted(() => {
  document.removeEventListener("keydown", closeMenusOnEscape);
  document.removeEventListener("pointerdown", closeGroupOnOutsideClick);
});
</script>

<template>
  <header class="sticky top-0 z-40 border-b border-border bg-background/95 shadow-sm backdrop-blur">
    <div class="mx-auto flex max-w-7xl flex-wrap items-center gap-2 px-4 py-2 sm:gap-3 lg:h-16 lg:flex-nowrap lg:py-0">
      <RouterLink
        to="/"
        class="flex min-h-11 shrink-0 items-center gap-2 rounded-md px-1 font-semibold tracking-tight outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :aria-label="t('nav.home')"
        data-testid="portal-brand"
      >
        <span class="flex size-8 items-center justify-center overflow-hidden rounded-lg bg-primary text-primary-foreground" aria-hidden="true">
          <img v-if="siteIconUrl" :src="siteIconUrl" alt="" class="size-8 object-contain" data-testid="portal-brand-icon" />
          <svg v-else viewBox="0 0 24 24" class="size-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M7 3c0 4 10 4 10 9s-10 5-10 9" />
            <path d="M17 3c0 4-10 4-10 9s10 5 10 9" />
            <path d="M8.4 6.2h7.2M8.4 17.8h7.2M7 12h10" />
          </svg>
        </span>
        <span data-testid="portal-brand-name">{{ siteName }}</span>
        <span v-if="site.isInternal" class="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-800">
          {{ t("nav.internalBadge") }}
        </span>
      </RouterLink>

      <nav ref="navigationRef" class="mx-auto hidden items-center gap-1 lg:flex" :aria-label="t('nav.primaryNavigation')" data-testid="desktop-navigation">
        <template v-for="group in navGroups" :key="group.key">
          <RouterLink
            v-if="group.to"
            :to="group.to"
            class="min-h-10 rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
            :class="isActive(group.to) ? 'text-foreground' : 'text-muted-foreground'"
            :aria-current="isActive(group.to) ? 'page' : undefined"
            :data-testid="`nav-link-${group.key}`"
          >
            {{ t(group.labelKey) }}
          </RouterLink>
          <div v-else class="relative">
            <button
              type="button"
              class="flex min-h-10 items-center gap-1 rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
              :class="isGroupActive(group) ? 'text-foreground' : 'text-muted-foreground'"
              :aria-haspopup="'menu'"
              :aria-expanded="openGroup === group.key"
              :data-active="isGroupActive(group)"
              :data-testid="`nav-group-${group.key}`"
              @click="toggleGroup(group.key, $event)"
            >
              {{ t(group.labelKey) }}
              <svg viewBox="0 0 16 16" class="size-3.5 transition-transform" :class="openGroup === group.key ? 'rotate-180' : ''" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6">
                <path d="m3 6 5 5 5-5" />
              </svg>
            </button>
            <div v-if="openGroup === group.key" role="menu" class="absolute left-1/2 top-full z-50 mt-2 w-60 -translate-x-1/2 rounded-xl border border-border bg-card p-1.5 shadow-lg" :data-testid="`nav-menu-${group.key}`">
              <template v-for="(child, index) in group.children" :key="`${group.key}-${index}`">
                <div v-if="child.kind === 'separator'" class="my-1 h-px bg-border" aria-hidden="true" />
                <RouterLink
                  v-else
                  :to="child.to"
                  role="menuitem"
                  class="block min-h-10 rounded-lg px-3 py-2 text-sm text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                  :class="isActive(child.to) ? 'bg-muted font-medium text-foreground' : ''"
                  :data-testid="`nav-item-${group.key}-${index}`"
                  @click="openGroup = null"
                >
                  {{ t(child.labelKey) }}
                </RouterLink>
              </template>
            </div>
          </div>
        </template>
      </nav>

      <div class="ms-auto flex min-h-11 shrink-0 items-center gap-1 lg:ms-0">
        <button
          type="button"
          class="min-h-10 rounded-md border border-transparent px-3 text-sm font-medium text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          :aria-label="t('nav.switchLanguage')"
          data-testid="language-switch"
          @click="setLanguage(nextLanguage)"
        >
          {{ languageButtonText }}
        </button>
        <button
          ref="mobileTrigger"
          type="button"
          class="flex size-11 items-center justify-center rounded-md border border-border text-foreground outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring lg:hidden"
          :aria-label="mobileOpen ? t('nav.closeMenu') : t('nav.openMenu')"
          :aria-expanded="mobileOpen"
          aria-controls="mobile-navigation"
          data-testid="mobile-menu-toggle"
          @click="mobileOpen = !mobileOpen"
        >
          <svg v-if="!mobileOpen" viewBox="0 0 24 24" class="size-5" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
          <svg v-else viewBox="0 0 24 24" class="size-5" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      </div>

      <form class="order-3 flex w-full gap-2 pb-1 sm:order-none sm:ms-auto sm:w-auto sm:pb-0" role="search" @submit.prevent="submitSearch">
        <label class="sr-only" for="portal-search">{{ t("nav.search") }}</label>
        <input
          id="portal-search"
          v-model="query"
          class="min-h-10 min-w-0 flex-1 rounded-md border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring sm:w-40 sm:flex-none lg:w-48"
          :placeholder="t('search.placeholder')"
          data-testid="portal-search-input"
        />
        <button type="submit" class="min-h-10 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground outline-none hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring" data-testid="portal-search-submit">
          {{ t("nav.search") }}
        </button>
      </form>
    </div>

    <nav v-if="mobileOpen" id="mobile-navigation" class="border-t border-border bg-card px-4 py-3 lg:hidden" :aria-label="t('nav.mobileNavigation')" data-testid="mobile-navigation">
      <div v-for="group in navGroups" :key="group.key" class="border-b border-border/70 py-2 last:border-b-0">
        <RouterLink
          v-if="group.to"
          :to="group.to"
          class="block min-h-11 rounded-md px-3 py-2 font-medium outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
          :aria-current="isActive(group.to) ? 'page' : undefined"
          data-testid="mobile-nav-first-link"
          @click="closeMobileMenu()"
        >
          {{ t(group.labelKey) }}
        </RouterLink>
        <template v-else>
          <p class="px-3 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{{ t(group.labelKey) }}</p>
          <div class="grid grid-cols-2 gap-1">
            <template v-for="(child, index) in group.children" :key="`${group.key}-${index}`">
              <div v-if="child.kind === 'separator'" class="col-span-2 my-1 h-px bg-border" aria-hidden="true" />
              <RouterLink
                v-else
                :to="child.to"
                class="flex min-h-11 items-center rounded-md px-3 py-2 text-sm text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                :class="isActive(child.to) ? 'font-medium text-foreground' : ''"
                :data-testid="`mobile-nav-item-${group.key}-${index}`"
                @click="closeMobileMenu()"
              >
                {{ t(child.labelKey) }}
              </RouterLink>
            </template>
          </div>
        </template>
      </div>
    </nav>

    <p class="border-t border-border/60 px-4 py-1.5 text-center text-xs text-muted-foreground" data-testid="portal-context">
      {{ t("releases.title") }}: {{ site.releaseId ?? t("releases.active") }} · {{ site.siteVariant }}
    </p>
  </header>
</template>
