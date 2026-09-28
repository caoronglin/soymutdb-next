<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useTemplateRef, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import IconGlyph from "./visuals/IconGlyph.vue";
import PortalNotificationBell from "./PortalNotificationBell.vue";
import { currentLanguage, setLanguage, t } from "../lib/i18n";
import { useSiteBranding } from "../lib/branding";
import { isJbrowseEnabled } from "../lib/deployment";
import { useSiteContent } from "../lib/site-content";
import { usePortalTheme } from "../lib/theme";
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
// than left as a link into a 502. The routes themselves are gated by component
// key in router/index.ts so a deep link (including /search/gbrowse) explains why.
const JBROWSE_ROUTES = ["/browser", "/search/gbrowse"] as const;
const disabledRoutes = new Set<string>(isJbrowseEnabled() ? [] : JBROWSE_ROUTES);
const navGroups = computed<readonly NavigationGroup[]>(() =>
  NAV_GROUPS.map((group) => ({
    ...group,
    children: group.children?.filter(
      (child) => child.kind !== "link" || !disabledRoutes.has(child.to),
    ),
  })),
);

/** Live React header links to the public repository from the GitHub glyph. */
const REPOSITORY_URL = "https://github.com/caoronglin/soymutdb-next";

const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();
const { displayName: siteName, iconUrl: siteIconUrl } = useSiteBranding();
const { get } = useSiteContent();

/**
 * Nav keys registered by apps/api/app/core/settings_registry.py. A label whose
 * key is not registered (nav.mutantLines, the tools.*.title page titles) stays
 * i18n-only; a registered one lets an operator override it per site variant.
 */
const EDITABLE_NAV_KEYS = new Set([
  "nav.home",
  "nav.search",
  "nav.tools",
  "nav.latestNews",
  "nav.contact",
  "nav.explore",
  "nav.resources",
  "nav.downloads",
  "nav.allTools",
  "nav.genes",
  "nav.variants",
  "nav.browser",
  "nav.blast",
  "nav.analyses",
  "nav.sra",
  "nav.compare",
  "nav.analytics",
  "nav.guide",
  "nav.help",
  "nav.news",
  "nav.publications",
  "nav.seedRequest",
  "nav.about",
]);

/** Resolve a nav label to its stored override, else the localized string. */
function navLabel(labelKey: string): string {
  return EDITABLE_NAV_KEYS.has(labelKey) ? get(labelKey, t(labelKey)) : t(labelKey);
}
const query = ref("");
const openGroup = ref<string | null>(null);
const mobileOpen = ref(false);
const scrolled = ref(false);
const navigationRef = ref<HTMLElement | null>(null);
const menuTrigger = ref<HTMLButtonElement | null>(null);
const mobileTrigger = ref<HTMLButtonElement | null>(null);
const searchInputRef = useTemplateRef<HTMLInputElement>("searchInputRef");

// The document theme is shared state: the header owns the toggle, PortalLayout
// feeds the same value to the AntD ConfigProvider.
const { theme, toggleTheme, applyTheme } = usePortalTheme();
const isDark = computed(() => theme.value === "dark");

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

function onScroll() {
  scrolled.value = window.scrollY > 8;
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
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  // The stored preference is read when the theme module initialises; mirror it
  // onto <html> once the document exists.
  applyTheme(theme.value);
});

onUnmounted(() => {
  document.removeEventListener("keydown", closeMenusOnEscape);
  document.removeEventListener("pointerdown", closeGroupOnOutsideClick);
  window.removeEventListener("scroll", onScroll);
});
</script>

<template>
  <header
    class="sticky top-0 z-40 border-b border-border bg-background/95 shadow-sm backdrop-blur"
    :class="scrolled ? 'site-header--scrolled' : ''"
  >
    <div class="mx-auto flex max-w-7xl flex-wrap items-center gap-2 px-4 py-2 sm:gap-3 lg:h-16 lg:flex-nowrap lg:py-0">
      <RouterLink
        to="/"
        class="flex min-h-11 shrink-0 items-center gap-2 rounded-md px-1 font-semibold tracking-tight outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :aria-label="navLabel('nav.home')"
        data-testid="portal-brand"
      >
        <span
          class="flex size-8 items-center justify-center overflow-hidden rounded-lg bg-gradient-to-br from-[var(--primary-gradient-start)] to-[var(--primary-gradient-end)] text-lg text-primary-foreground shadow-sm"
          aria-hidden="true"
        >
          <img v-if="siteIconUrl" :src="siteIconUrl" alt="" class="size-8 object-contain" data-testid="portal-brand-icon" />
          <IconGlyph v-else name="leaf" />
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
            class="nav-link min-h-10 rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring"
            :class="isActive(group.to) ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'"
            :data-active="isActive(group.to)"
            :aria-current="isActive(group.to) ? 'page' : undefined"
            :data-testid="`nav-link-${group.key}`"
          >
            {{ navLabel(group.labelKey) }}
          </RouterLink>
          <div v-else class="relative">
            <button
              type="button"
              class="nav-link flex min-h-10 items-center gap-1 rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring"
              :class="isGroupActive(group) ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'"
              :aria-haspopup="'menu'"
              :aria-expanded="openGroup === group.key"
              :data-active="isGroupActive(group)"
              :data-testid="`nav-group-${group.key}`"
              @click="toggleGroup(group.key, $event)"
            >
              {{ navLabel(group.labelKey) }}
              <IconGlyph name="chevron-down" class="text-xs transition-transform" :class="openGroup === group.key ? 'rotate-180' : ''" />
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
                  {{ navLabel(child.labelKey) }}
                </RouterLink>
              </template>
            </div>
          </div>
        </template>
      </nav>

      <div class="ms-auto flex min-h-11 shrink-0 items-center gap-1 lg:ms-0">
        <button
          type="button"
          class="hidden min-h-9 items-center gap-2 rounded-lg border border-input/70 bg-muted/40 px-3 text-sm text-muted-foreground outline-none transition-colors hover:border-border hover:bg-muted/70 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring xl:flex"
          :aria-label="t('nav.quickSearch')"
          data-testid="portal-search-trigger"
          @click="searchInputRef?.focus()"
        >
          <IconGlyph name="search" class="text-base" />
          <span class="hidden lg:inline">{{ t("home.searchPlaceholder") }}</span>
        </button>

        <PortalNotificationBell />

        <button
          type="button"
          class="min-h-10 rounded-md border border-transparent px-2 text-sm font-medium text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          :aria-label="t('nav.switchLanguage')"
          data-testid="language-switch"
          @click="setLanguage(nextLanguage)"
        >
          {{ languageButtonText }}
        </button>

        <button
          type="button"
          class="flex size-10 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          :aria-label="t('nav.theme')"
          :aria-pressed="isDark"
          data-testid="theme-toggle"
          @click="toggleTheme"
        >
          <IconGlyph :name="isDark ? 'sun' : 'moon'" class="text-lg" />
        </button>

        <a
          :href="REPOSITORY_URL"
          target="_blank"
          rel="noreferrer"
          class="hidden size-10 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring sm:flex"
          :aria-label="t('nav.repository')"
          data-testid="portal-github"
        >
          <IconGlyph name="github" class="text-lg" />
        </a>

        <button
          type="button"
          class="hidden size-10 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring sm:flex"
          :aria-label="t('nav.adminConsole')"
          :aria-disabled="true"
          data-testid="portal-admin-entry"
        >
          <IconGlyph name="grid" class="text-lg" />
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
          <IconGlyph :name="mobileOpen ? 'close' : 'menu'" class="text-lg" />
        </button>
      </div>

      <form class="order-3 flex w-full gap-2 pb-1 sm:order-none sm:ms-auto sm:w-auto sm:pb-0" role="search" @submit.prevent="submitSearch">
        <label class="sr-only" for="portal-search">{{ navLabel("nav.search") }}</label>
        <div class="relative flex flex-1 items-center sm:flex-none">
          <input
            id="portal-search"
            ref="searchInputRef"
            v-model="query"
            type="search"
            class="min-h-10 w-full rounded-lg border border-input/70 bg-card pl-3 pr-12 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring sm:w-44 lg:w-56"
            :placeholder="t('search.placeholder')"
            aria-keyshortcuts="Meta+K Control+K"
            data-testid="portal-search-input"
          />
          <kbd class="pointer-events-none absolute right-3 hidden items-center gap-0.5 rounded border border-border bg-muted/60 px-1 text-[10px] font-medium text-muted-foreground sm:flex" aria-hidden="true">⌘K</kbd>
        </div>
        <button type="submit" class="min-h-10 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground outline-none hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring" data-testid="portal-search-submit">
          {{ navLabel("nav.search") }}
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
          {{ navLabel(group.labelKey) }}
        </RouterLink>
        <template v-else>
          <p class="px-3 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{{ navLabel(group.labelKey) }}</p>
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
                {{ navLabel(child.labelKey) }}
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
