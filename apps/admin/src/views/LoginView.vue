<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { Button, ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { useAuth } from "../lib/auth";
import { t } from "../lib/i18n";

/**
 * Admin sign-in.
 *
 * The console has no public surface, so the error copy stays generic: a message
 * that distinguishes "no such account" from "wrong password" is an account
 * enumeration oracle, and the admin realm is exactly where that matters.
 */
const route = useRoute();
const router = useRouter();
const auth = useAuth();

const identifier = ref("");
const password = ref("");
const errorMessage = ref("");
const isPending = ref(false);

const redirectTarget = computed(() => {
  const value = route.query.redirect;
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return "/";
  return value;
});

async function submit() {
  if (isPending.value) return;
  isPending.value = true;
  errorMessage.value = "";
  try {
    await auth.login(identifier.value.trim(), password.value);
    await router.push(redirectTarget.value);
  } catch {
    errorMessage.value = t("auth.invalidCredentials");
  } finally {
    isPending.value = false;
  }
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <main class="mx-auto max-w-sm px-4 py-16">
      <h1 class="text-2xl font-semibold">{{ t("admin.title") }}</h1>
      <p class="mt-1 text-sm opacity-70">{{ t("loginPage.adminHint") }}</p>

      <form class="mt-6 grid gap-4" @submit.prevent="submit">
        <label class="text-sm opacity-70">
          {{ t("auth.username") }}
          <input
            v-model="identifier"
            autocomplete="username"
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            data-testid="admin-identifier"
          />
        </label>
        <label class="text-sm opacity-70">
          {{ t("auth.password") }}
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            data-testid="admin-password"
          />
        </label>
        <p v-if="errorMessage" role="alert" data-testid="admin-login-error" class="text-sm text-red-700">
          {{ errorMessage }}
        </p>
        <Button html-type="submit" :disabled="isPending" data-testid="admin-login-submit">
          {{ isPending ? t("common.loading") : t("auth.loginButton") }}
        </Button>
      </form>
    </main>
  </ConfigProvider>
</template>
