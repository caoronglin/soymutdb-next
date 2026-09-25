<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import { Button, ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { useAuth } from "../lib/auth";
import { ADMIN_ROUTES } from "../router";

/**
 * Console chrome: navigation, the signed-in identity, and the release the
 * console is operating on. The release is shown because every mutating action
 * here is scoped to it — an operator who cannot see which release they are
 * about to publish to is one mis-click away from publishing to the wrong one.
 */
const route = useRoute();
const router = useRouter();
const auth = useAuth();

const navItems = computed(() =>
  ADMIN_ROUTES.filter((item) => item.nav).map((item) => ({
    path: item.path,
    label: item.nav as string,
  })),
);

const releaseId = import.meta.env.VITE_SOYMUTDB_RELEASE_ID ?? "active";

function isActive(path: string): boolean {
  return route.path === path;
}

function signOut() {
  auth.logout();
  void router.push({ name: "login" });
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="flex min-h-screen bg-background text-foreground">
      <aside class="w-60 shrink-0 border-r p-4" aria-label="Admin navigation">
        <p class="font-semibold">SoyMutDB admin</p>
        <p class="mt-1 text-xs opacity-70" data-testid="admin-release">
          release: {{ releaseId }}
        </p>
        <nav class="mt-4 grid gap-1">
          <RouterLink
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            class="rounded-md px-2 py-1.5 text-sm"
            :class="isActive(item.path) ? 'bg-black/5 font-medium' : 'opacity-70 hover:opacity-100'"
            :data-testid="'nav-' + item.path.replace(/^\//, '').replace(/\//g, '-')"
          >
            {{ item.label }}
          </RouterLink>
        </nav>
      </aside>

      <div class="flex min-w-0 flex-1 flex-col">
        <header class="flex items-center justify-between border-b px-4 py-3">
          <p class="text-sm opacity-70">
            Signed in as <span class="font-medium">{{ auth.username.value ?? "administrator" }}</span>
            <Tag v-if="auth.isAuthenticated.value" color="green">session</Tag>
          </p>
          <Button size="small" data-testid="admin-sign-out" @click="signOut">Sign out</Button>
        </header>
        <main class="min-w-0 flex-1 p-6">
          <slot />
        </main>
      </div>
    </div>
  </ConfigProvider>
</template>
