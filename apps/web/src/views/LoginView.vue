<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useQueryClient } from "@tanstack/vue-query";

import { ApiError, request, setAccessToken } from "@soymutdb/api-client";

import { currentLanguage, setLanguage, t } from "../lib/i18n";
import { safeRedirect } from "../lib/redirect";

interface LoginResponse {
  access_token: string;
}

const route = useRoute();
const router = useRouter();
const queryClient = useQueryClient();
const email = ref("");
const password = ref("");
const errorMessage = ref("");
const isPending = ref(false);
const redirectTarget = computed(() => safeRedirect(route.query.redirect));
const nextLanguage = computed(() => (currentLanguage.value === "zh" ? "en" : "zh"));
const languageButtonText = computed(() => (currentLanguage.value === "zh" ? "EN" : "中文"));

async function submit() {
  if (isPending.value) return;
  isPending.value = true;
  errorMessage.value = "";

  try {
    // Login uses the raw unauthenticated request path: an expected 401 must not
    // trigger refresh, clear session state, or emit a global logout event.
    const response = await request<LoginResponse>("/auth/login", {
      method: "POST",
      json: { email: email.value.trim(), password: password.value },
      auth: false,
      withCredentials: true,
    });
    if (!response.access_token) throw new Error("Login response omitted access token");

    setAccessToken(response.access_token);
    queryClient.removeQueries({ queryKey: ["current-user"], exact: true });
    await router.push(redirectTarget.value);
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError && (error.status === 401 || error.status === 403)
        ? t("auth.invalidCredentials")
        : t("loginPage.loginUnavailable");
  } finally {
    isPending.value = false;
  }
}
</script>

<template>
  <main class="grid min-h-screen bg-background text-foreground lg:grid-cols-[0.86fr_1.14fr]">
    <aside class="relative hidden min-h-screen flex-col justify-between overflow-hidden bg-primary p-10 text-primary-foreground lg:flex xl:p-14" data-testid="login-brand-panel">
      <div class="pointer-events-none absolute -right-28 -top-28 size-96 rounded-full border border-white/15" aria-hidden="true" />
      <div class="pointer-events-none absolute -bottom-48 -left-40 size-[34rem] rounded-full border border-white/10" aria-hidden="true" />
      <div class="pointer-events-none absolute inset-0 flex items-center justify-center opacity-[0.12]" aria-hidden="true">
        <svg viewBox="0 0 240 500" class="h-[72%] max-h-[34rem] w-auto" fill="none" stroke="currentColor" stroke-width="3">
          <path d="M54 20c0 95 132 95 132 190S54 305 54 480" />
          <path d="M186 20c0 95-132 95-132 190s132 95 132 270" />
          <path d="M72 74h96M61 126h118M54 210h132M54 290h132M61 374h118M72 426h96" />
        </svg>
      </div>

      <RouterLink to="/" class="relative flex min-h-11 items-center gap-3 self-start rounded-md outline-none focus-visible:ring-2 focus-visible:ring-primary-foreground" :aria-label="t('nav.home')">
        <span class="flex size-10 items-center justify-center rounded-xl bg-white/15" aria-hidden="true">
          <svg viewBox="0 0 24 24" class="size-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M7 3c0 4 10 4 10 9s-10 5-10 9" />
            <path d="M17 3c0 4-10 4-10 9s10 5 10 9" />
            <path d="M8.4 6.2h7.2M8.4 17.8h7.2M7 12h10" />
          </svg>
        </span>
        <span class="text-lg font-semibold tracking-tight">SoyMutDB</span>
      </RouterLink>

      <div class="relative max-w-lg py-12">
        <p class="text-4xl font-semibold leading-tight tracking-tight xl:text-5xl">{{ t("loginPage.brandTitle") }}</p>
        <p class="mt-5 max-w-md text-base leading-7 text-primary-foreground/85">{{ t("loginPage.brandTagline") }}</p>
        <ul class="mt-8 grid gap-4">
          <li v-for="item in ['variants', 'browser', 'analytics']" :key="item" class="flex items-center gap-3 text-sm text-primary-foreground/95">
            <span class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white/15" aria-hidden="true">
              <svg v-if="item === 'variants'" viewBox="0 0 24 24" class="size-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="m4 16 5-5 3 3 7-8" /><path d="M14 6h5v5" /></svg>
              <svg v-else-if="item === 'browser'" viewBox="0 0 24 24" class="size-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9" /><path d="M3.5 9h17M9 3.5c-2 5.7-2 11.3 0 17M15 3.5c2 5.7 2 11.3 0 17" /></svg>
              <svg v-else viewBox="0 0 24 24" class="size-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 19V5M4 19h17M8 15l3-4 3 2 5-7" /></svg>
            </span>
            {{ t(`loginPage.brandBullets.${item}`) }}
          </li>
        </ul>
      </div>

      <ul class="relative grid gap-2 text-xs text-primary-foreground/75">
        <li>{{ t("loginPage.secureNote") }}</li>
        <li>{{ t("loginPage.twoFactorHint") }}</li>
        <li>{{ t("loginPage.sessionNote") }}</li>
      </ul>
    </aside>

    <section class="flex min-h-screen flex-col">
      <div class="flex min-h-16 items-center justify-between px-5 sm:px-8 lg:justify-end lg:px-10" data-testid="login-topbar">
        <RouterLink to="/" class="flex min-h-11 items-center gap-2 font-semibold tracking-tight outline-none focus-visible:ring-2 focus-visible:ring-ring lg:hidden" :aria-label="t('nav.home')">
          <span class="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground" aria-hidden="true">
            <svg viewBox="0 0 24 24" class="size-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M7 3c0 4 10 4 10 9s-10 5-10 9" />
              <path d="M17 3c0 4-10 4-10 9s10 5 10 9" />
              <path d="M8.4 6.2h7.2M8.4 17.8h7.2M7 12h10" />
            </svg>
          </span>
          SoyMutDB
        </RouterLink>
        <div class="flex items-center gap-4">
          <RouterLink to="/" class="hidden min-h-11 items-center gap-1 rounded-md px-2 text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring sm:inline-flex" data-testid="login-back-home">
            <svg viewBox="0 0 16 16" class="size-4" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10.5 3 5.5 8l5 5" /></svg>
            {{ t("loginPage.backHome") }}
          </RouterLink>
          <button type="button" class="min-h-11 rounded-md px-3 text-sm font-medium text-muted-foreground outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring" :aria-label="t('nav.switchLanguage')" data-testid="login-language-switch" @click="setLanguage(nextLanguage)">
            {{ languageButtonText }}
          </button>
        </div>
      </div>

      <div class="flex flex-1 items-center justify-center px-4 pb-10 sm:px-8 lg:px-10">
        <div class="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-sm sm:p-8" data-testid="login-form-panel">
          <p class="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{{ t("loginPage.welcomeBack") }}</p>
          <h1 class="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{{ t("loginPage.title") }}</h1>
          <p class="mt-2 text-sm leading-6 text-muted-foreground">{{ t("loginPage.subtitle") }}</p>

          <form class="mt-7 grid gap-5" @submit.prevent="submit" data-testid="login-form">
            <label for="login-email" class="grid gap-2 text-sm font-medium">
              {{ t("auth.email") }}
              <input id="login-email" v-model="email" type="email" autocomplete="username" required class="min-h-11 w-full rounded-md border border-border bg-background px-3 text-base font-normal outline-none transition focus-visible:ring-2 focus-visible:ring-ring" :placeholder="t('auth.emailPlaceholder')" data-testid="login-email" />
            </label>
            <label for="login-password" class="grid gap-2 text-sm font-medium">
              {{ t("auth.password") }}
              <input id="login-password" v-model="password" type="password" autocomplete="current-password" required class="min-h-11 w-full rounded-md border border-border bg-background px-3 text-base font-normal outline-none transition focus-visible:ring-2 focus-visible:ring-ring" data-testid="login-password" />
            </label>
            <p v-if="errorMessage" class="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert" data-testid="login-error">
              {{ errorMessage }}
            </p>
            <button type="submit" class="min-h-11 rounded-md bg-primary px-4 font-medium text-primary-foreground outline-none transition hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60" :disabled="isPending" data-testid="login-submit">
              {{ isPending ? t("common.loading") : t("auth.loginButton") }}
            </button>
          </form>

          <p class="mt-6 border-t border-border pt-5 text-xs leading-5 text-muted-foreground lg:hidden">
            {{ t("loginPage.secureNote") }}
          </p>
        </div>
      </div>
    </section>
  </main>
</template>
