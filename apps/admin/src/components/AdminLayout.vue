<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { Button, ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import InstanceContextBadge from "./InstanceContextBadge.vue";
import { currentLanguage, t } from "../lib/i18n";
import { useAuth } from "../lib/auth";
import { ADMIN_ROUTES } from "../router";

const route = useRoute();
const router = useRouter();
const auth = useAuth();
const sidebarOpen = ref(false);
const releaseId = import.meta.env.VITE_SOYMUTDB_RELEASE_ID ?? "active";

const navItems = computed(() => {
  currentLanguage.value;
  return ADMIN_ROUTES.filter((item) => item.navKey).map((item) => ({
    path: item.path as string,
    label: t(item.navKey as string),
  }));
});

watch(() => route.path, () => {
  sidebarOpen.value = false;
});

function isActive(path: string): boolean {
  return path === "/" ? route.path === path : route.path === path || route.path.startsWith(`${path}/`);
}

function signOut() {
  auth.logout();
  void router.push({ name: "login" });
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="min-h-screen bg-background text-foreground lg:flex">
      <button
        v-if="sidebarOpen"
        type="button"
        class="fixed inset-0 z-30 bg-slate-950/35 lg:hidden"
        :aria-label="t('common.close')"
        data-testid="admin-sidebar-backdrop"
        @click="sidebarOpen = false"
      />

      <aside
        id="admin-sidebar"
        :aria-label="t('admin.navigation')"
        class="fixed inset-y-0 left-0 z-40 flex w-[min(18rem,86vw)] -translate-x-full flex-col border-r border-border bg-card px-4 py-5 shadow-xl transition-transform duration-200 lg:static lg:z-auto lg:w-60 lg:shrink-0 lg:translate-x-0 lg:shadow-none"
        :class="sidebarOpen ? 'translate-x-0' : ''"
        data-testid="admin-sidebar"
      >
        <div class="flex items-center gap-3 px-2">
          <div class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <svg aria-hidden="true" viewBox="0 0 24 24" class="size-5" fill="none">
              <path d="M12 3.25 19 6v5.2c0 4.34-2.9 7.7-7 9.55-4.1-1.85-7-5.21-7-9.55V6l7-2.75Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" />
              <path d="m8.6 12.1 2.2 2.2 4.7-4.9" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
          <div class="min-w-0">
            <p class="truncate text-sm font-semibold">{{ t("admin.title") }}</p>
            <p class="mt-0.5 truncate text-xs text-muted-foreground">
              {{ t("releases.releaseName") }} · {{ releaseId }}
            </p>
          </div>
        </div>

        <nav class="mt-7 flex-1 space-y-1 overflow-y-auto" :aria-label="t('admin.title')">
          <RouterLink
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            class="flex min-h-10 items-center rounded-lg border-l-2 px-3 text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :class="isActive(item.path)
              ? 'border-primary bg-primary/10 font-medium text-primary'
              : 'border-transparent text-muted-foreground hover:bg-muted hover:text-foreground'"
            :data-testid="'nav-' + item.path.replace(/^\//, '').replace(/\//g, '-')"
            @click="sidebarOpen = false"
          >
            {{ item.label }}
          </RouterLink>
        </nav>

        <div class="mt-4 border-t border-border px-2 pt-4 text-xs text-muted-foreground">
          SoyMutDB
        </div>
      </aside>

      <div class="flex min-h-screen min-w-0 flex-1 flex-col">
        <header class="sticky top-0 z-20 flex min-h-14 items-center justify-between gap-3 border-b border-border bg-card/95 px-4 backdrop-blur sm:px-6">
          <div class="flex min-w-0 items-center gap-3">
            <button
              type="button"
              class="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:hidden"
              :aria-label="t('admin.navigation')"
              aria-controls="admin-sidebar"
              :aria-expanded="sidebarOpen"
              data-testid="admin-menu-toggle"
              @click="sidebarOpen = !sidebarOpen"
            >
              <svg v-if="!sidebarOpen" aria-hidden="true" viewBox="0 0 24 24" class="size-5" fill="none">
                <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
              </svg>
              <svg v-else aria-hidden="true" viewBox="0 0 24 24" class="size-5" fill="none">
                <path d="m6 6 12 12M18 6 6 18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
              </svg>
            </button>
            <div class="min-w-0">
              <p class="truncate text-sm font-medium">{{ t("admin.title") }}</p>
              <p class="truncate text-xs text-muted-foreground">
                {{ t("auth.username") }}: {{ auth.username.value ?? "—" }}
              </p>
            </div>
          </div>
          <div class="flex flex-wrap items-center justify-end gap-2 sm:gap-3">
            <InstanceContextBadge />
            <Button size="small" data-testid="admin-sign-out" @click="signOut">
              {{ t("auth.logout") }}
            </Button>
          </div>
        </header>

        <main class="min-w-0 flex-1 p-4 sm:p-6 lg:p-7">
          <slot />
        </main>
      </div>
    </div>
  </ConfigProvider>
</template>
