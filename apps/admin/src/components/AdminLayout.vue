<template>
  <div class="flex h-screen overflow-hidden bg-background text-foreground">
    <!-- Desktop sidebar: collapses to an icon rail, never disappears. -->
    <aside
      class="admin-sidebar-scroll hidden h-full shrink-0 flex-col border-r border-border bg-card transition-[width] duration-200 lg:flex"
      :class="collapsed ? 'w-16' : 'w-64'"
      :aria-label="t('admin.shell.navigationAria', { defaultValue: 'Admin navigation' })"
      data-testid="admin-sidebar"
    >
      <div class="flex h-14 items-center gap-2 border-b border-border px-4">
        <span
          class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground"
        >
          <AdminBrandMark />
        </span>
        <div v-if="!collapsed" class="min-w-0">
          <p class="truncate font-serif text-sm font-semibold">SoyMutDB</p>
          <p class="truncate text-xs text-muted-foreground">
            {{ t("admin.title", { defaultValue: "Admin Console" }) }}
          </p>
        </div>
      </div>

      <nav class="admin-sidebar-scroll flex-1 overflow-y-auto py-3">
        <div v-for="section in navSections" :key="section.labelKey" class="mb-4">
          <p v-if="!collapsed" class="admin-nav-section-label">
            {{ section.label }}
          </p>
          <ul class="space-y-0.5 px-2">
            <li v-for="item in section.items" :key="item.path">
              <RouterLink
                :to="item.path"
                class="admin-nav-item flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                :class="[
                  isActive(item.path)
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                  collapsed && 'justify-center',
                ]"
                :data-active="isActive(item.path)"
                :title="collapsed ? item.label : undefined"
                :aria-current="isActive(item.path) ? 'page' : undefined"
                :data-testid="'nav-' + item.path.replace(/^\//, '').replace(/\//g, '-')"
              >
                <svg aria-hidden="true" viewBox="0 0 24 24" class="size-4 shrink-0" fill="none">
                  <path
                    v-for="(d, index) in item.icon"
                    :key="index"
                    :d="d"
                    stroke="currentColor"
                    stroke-width="1.6"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
                <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
              </RouterLink>
            </li>
          </ul>
        </div>
      </nav>

      <div class="border-t border-border p-2">
        <button
          type="button"
          class="flex w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :aria-label="
            collapsed
              ? t('admin.shell.expandSidebar', { defaultValue: 'Expand sidebar' })
              : t('admin.shell.collapseSidebar', { defaultValue: 'Collapse sidebar' })
          "
          :aria-expanded="!collapsed"
          data-testid="admin-sidebar-collapse"
          @click="collapsed = !collapsed"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" class="size-4" fill="none">
            <path
              :d="collapsed ? 'm10 7 5 5-5 5' : 'm14 7-5 5 5 5'"
              stroke="currentColor"
              stroke-width="1.7"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <span v-if="!collapsed">
            {{ t("admin.shell.collapse", { defaultValue: "Collapse" }) }}
          </span>
        </button>
      </div>
    </aside>

    <!-- Mobile sidebar: an overlay, so a narrow screen keeps full content width. -->
    <div v-if="mobileOpen" class="fixed inset-0 z-40 lg:hidden">
      <div class="absolute inset-0 bg-black/50" aria-hidden="true" @click="mobileOpen = false" />
      <aside
        id="admin-sidebar"
        class="absolute left-0 top-0 flex h-full w-[min(18rem,86vw)] flex-col border-r border-border bg-card"
        :aria-label="t('admin.shell.navigationAria', { defaultValue: 'Admin navigation' })"
        data-testid="admin-sidebar-mobile"
      >
        <div class="flex h-14 items-center gap-2 border-b border-border px-4">
          <span
            class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground"
          >
            <AdminBrandMark />
          </span>
          <div class="min-w-0">
            <p class="truncate font-serif text-sm font-semibold">SoyMutDB</p>
            <p class="truncate text-xs text-muted-foreground">
              {{ t("admin.title", { defaultValue: "Admin Console" }) }}
            </p>
          </div>
        </div>
        <nav class="admin-sidebar-scroll flex-1 overflow-y-auto py-3">
          <div v-for="section in navSections" :key="section.labelKey" class="mb-4">
            <p class="admin-nav-section-label">{{ section.label }}</p>
            <ul class="space-y-0.5 px-2">
              <li v-for="item in section.items" :key="item.path">
                <RouterLink
                  :to="item.path"
                  class="admin-nav-item flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors"
                  :class="
                    isActive(item.path)
                      ? 'bg-primary/10 font-medium text-primary'
                      : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                  "
                  :data-active="isActive(item.path)"
                  :aria-current="isActive(item.path) ? 'page' : undefined"
                  @click="mobileOpen = false"
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24" class="size-4 shrink-0" fill="none">
                    <path
                      v-for="(d, index) in item.icon"
                      :key="index"
                      :d="d"
                      stroke="currentColor"
                      stroke-width="1.6"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                  <span class="truncate">{{ item.label }}</span>
                </RouterLink>
              </li>
            </ul>
          </div>
        </nav>
      </aside>
    </div>

    <div class="flex min-w-0 flex-1 flex-col">
      <header
        class="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card/95 px-4 backdrop-blur"
      >
        <button
          type="button"
          class="flex size-9 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:hidden"
          :aria-label="t('admin.shell.toggleSidebarAria', { defaultValue: 'Toggle sidebar' })"
          aria-controls="admin-sidebar"
          :aria-expanded="mobileOpen"
          data-testid="admin-menu-toggle"
          @click="mobileOpen = !mobileOpen"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" class="size-5" fill="none">
            <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          </svg>
        </button>

        <h1 class="min-w-0 truncate font-serif text-lg font-semibold" data-testid="admin-page-title">
          {{ pageTitle }}
        </h1>

        <div class="ml-auto flex items-center gap-1">
          <button
            type="button"
            class="hidden items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted sm:inline-flex"
            :aria-label="t('admin.shell.openCommandPalette', { defaultValue: 'Open command palette' })"
            data-testid="admin-command-open"
            @click="paletteOpen = true"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" class="size-3.5" fill="none">
              <circle cx="11" cy="11" r="6" stroke="currentColor" stroke-width="1.7" />
              <path d="m15.5 15.5 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
            </svg>
            {{ t("admin.shell.commandPalette", { defaultValue: "Commands" }) }}
            <kbd class="rounded border border-border px-1 text-[10px]">⌘K</kbd>
          </button>

          <button
            type="button"
            class="flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            :aria-label="
              theme === 'light'
                ? t('admin.shell.toggleThemeToDark', { defaultValue: 'Switch to dark theme' })
                : t('admin.shell.toggleThemeToLight', { defaultValue: 'Switch to light theme' })
            "
            data-testid="admin-theme-toggle"
            @click="toggleTheme"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" class="size-4" fill="none">
              <template v-if="theme === 'light'">
                <path
                  d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9V16h7v-2.1A6 6 0 0 0 12 3Z"
                  stroke="currentColor"
                  stroke-width="1.6"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </template>
              <template v-else>
                <circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.6" />
                <path
                  d="M12 3v2m0 14v2M4.2 4.2l1.4 1.4m12.8 12.8 1.4 1.4M3 12h2m14 0h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"
                  stroke="currentColor"
                  stroke-width="1.6"
                  stroke-linecap="round"
                />
              </template>
            </svg>
          </button>

          <AdminNotificationBell />

          <div ref="userMenu" class="relative">
            <button
              type="button"
              class="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent"
              :aria-label="t('admin.shell.userMenuAria', { defaultValue: 'User menu' })"
              :aria-expanded="userMenuOpen"
              data-testid="admin-user-menu"
              @click="userMenuOpen = !userMenuOpen"
            >
              <span
                class="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
              >
                {{ initials }}
              </span>
              <span class="hidden text-sm font-medium sm:inline">{{ username }}</span>
              <svg aria-hidden="true" viewBox="0 0 24 24" class="size-3.5 text-muted-foreground" fill="none">
                <path d="m7 10 5 5 5-5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
              </svg>
            </button>

            <div
              v-if="userMenuOpen"
              class="absolute right-0 top-full z-50 mt-2 w-56 overflow-hidden rounded-lg border border-border bg-popover shadow-lg"
              role="menu"
              data-testid="admin-user-panel"
            >
              <div class="border-b border-border px-4 py-3">
                <p class="text-sm font-semibold">{{ username }}</p>
                <p class="truncate text-xs text-muted-foreground">{{ t("admin.title", { defaultValue: "Admin Console" }) }}</p>
              </div>
              <ul class="py-1">
                <li>
                  <button
                    type="button"
                    role="menuitem"
                    class="flex w-full items-center gap-2.5 px-4 py-2 text-sm transition-colors hover:bg-accent"
                    data-testid="admin-profile"
                    @click="openProfile"
                  >
                    <svg aria-hidden="true" viewBox="0 0 24 24" class="size-4" fill="none">
                      <circle cx="12" cy="9" r="3.2" stroke="currentColor" stroke-width="1.6" />
                      <path d="M5.5 19.5a6.5 6.5 0 0 1 13 0" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
                    </svg>
                    {{ t("admin.shell.profile", { defaultValue: "Profile" }) }}
                  </button>
                </li>
                <li>
                  <button
                    type="button"
                    role="menuitem"
                    class="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-destructive transition-colors hover:bg-destructive/10"
                    data-testid="admin-sign-out"
                    @click="signOut"
                  >
                    <svg aria-hidden="true" viewBox="0 0 24 24" class="size-4" fill="none">
                      <path
                        d="M14 5.5H7.5v13H14M16.5 12H10m6.5 0-2.5-2.5m2.5 2.5L14 14.5"
                        stroke="currentColor"
                        stroke-width="1.6"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      />
                    </svg>
                    {{ t("admin.shell.signOut", { defaultValue: "Sign out" }) }}
                  </button>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </header>

      <main class="min-w-0 flex-1 overflow-y-auto">
        <div class="route-fade-in mx-auto max-w-7xl p-4 md:p-6">
          <slot />
        </div>
      </main>
    </div>

    <AdminCommandPalette v-model="paletteOpen" @navigate="navigateTo" @open-gene="openGene" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useTemplateRef, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AdminBrandMark from "./AdminBrandMark.vue";
import AdminCommandPalette from "./AdminCommandPalette.vue";
import AdminNotificationBell from "./AdminNotificationBell.vue";
import { adminTitleFor, ADMIN_NAV_SECTIONS } from "../lib/admin-nav";
import { useAuth } from "../lib/auth";
import { t, currentLanguage } from "../lib/i18n";
import { useAdminTheme } from "../lib/theme";

/**
 * Console shell: collapsible grouped sidebar + sticky top bar + scrolling
 * content column.
 *
 * Restores the React shell's shape (grouped sections, icon rail, page title,
 * theme toggle, notification bell, user menu, ⌘K palette, `b` shortcut). The Vue
 * port had flattened the sidebar to a single ungrouped list derived from the
 * route table, which dropped every page without a `navKey` from navigation.
 */
const route = useRoute();
const router = useRouter();
const auth = useAuth();
const { theme, toggleTheme } = useAdminTheme();

const collapsed = ref(false);
const mobileOpen = ref(false);
const paletteOpen = ref(false);
const userMenuOpen = ref(false);
const userMenu = useTemplateRef<HTMLElement>("userMenu");

const username = computed(() => auth.username.value ?? "—");
const initials = computed(() => username.value.slice(0, 2).toUpperCase());

const navSections = computed(() => {
  // `t` reads the language ref, so the subscription must be explicit.
  currentLanguage.value;
  return ADMIN_NAV_SECTIONS.map((section) => ({
    labelKey: section.labelKey,
    label: t(section.labelKey, { defaultValue: section.labelDefault }),
    items: section.items.map((item) => ({
      path: item.path,
      icon: item.icon,
      label: t(item.labelKey, { defaultValue: item.labelDefault }),
    })),
  }));
});

const pageTitle = computed(() => {
  currentLanguage.value;
  const entry = adminTitleFor(route.path);
  return entry
    ? t(entry.labelKey, { defaultValue: entry.labelDefault })
    : t("admin.title", { defaultValue: "Admin Console" });
});

watch(
  () => route.path,
  () => {
    mobileOpen.value = false;
    userMenuOpen.value = false;
  },
);

function isActive(path: string): boolean {
  return path === "/" ? route.path === "/" : route.path === path || route.path.startsWith(`${path}/`);
}

function navigateTo(path: string): void {
  void router.push(path);
}

/**
 * Gene records live on the portal, not in this router (the admin and portal are
 * separate bundles), so a gene result leaves the console — same as the React
 * palette did.
 */
function openGene(geneId: string): void {
  window.location.assign(`/genes/${encodeURIComponent(geneId)}`);
}

function openProfile(): void {
  userMenuOpen.value = false;
  void router.push("/settings");
}

function signOut(): void {
  auth.logout();
  void router.push({ name: "login" });
}

function isEditableTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

function onKeyDown(event: KeyboardEvent): void {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    paletteOpen.value = !paletteOpen.value;
    return;
  }
  if (
    event.key.toLowerCase() === "b" &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.altKey &&
    !event.shiftKey &&
    !isEditableTarget(event.target)
  ) {
    event.preventDefault();
    collapsed.value = !collapsed.value;
  }
}

function onDocumentMouseDown(event: MouseEvent): void {
  if (userMenu.value && !userMenu.value.contains(event.target as Node)) userMenuOpen.value = false;
}

onMounted(() => {
  window.addEventListener("keydown", onKeyDown);
  document.addEventListener("mousedown", onDocumentMouseDown);
});
onUnmounted(() => {
  window.removeEventListener("keydown", onKeyDown);
  document.removeEventListener("mousedown", onDocumentMouseDown);
});
</script>
