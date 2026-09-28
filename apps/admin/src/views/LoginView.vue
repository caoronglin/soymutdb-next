<template>
  <main class="flex min-h-screen items-center justify-center bg-background px-4 py-12">
    <div class="w-full max-w-sm">
      <div class="flex items-center gap-3">
        <span
          class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm"
        >
          <AdminBrandMark />
        </span>
        <div class="min-w-0">
          <p class="truncate font-serif text-base font-semibold">SoyMutDB</p>
          <p class="truncate text-xs text-muted-foreground">
            {{ t("admin.title", { defaultValue: "Admin Console" }) }}
          </p>
        </div>
      </div>

      <AdminCard class="mt-4">
        <p class="text-sm text-muted-foreground">{{ t("loginPage.adminHint") }}</p>

        <form class="mt-4 grid gap-4" @submit.prevent="submit">
          <label class="admin-field">
            {{ t("auth.username") }}
            <input
              v-model="identifier"
              class="admin-control"
              autocomplete="username"
              data-testid="admin-identifier"
            />
          </label>
          <label class="admin-field">
            {{ t("auth.password") }}
            <input
              v-model="password"
              class="admin-control"
              type="password"
              autocomplete="current-password"
              data-testid="admin-password"
            />
          </label>

          <p
            v-if="errorMessage"
            role="alert"
            class="admin-state admin-state--error"
            data-testid="admin-login-error"
          >
            {{ errorMessage }}
          </p>

          <Button type="primary" html-type="submit" :disabled="isPending" data-testid="admin-login-submit">
            {{ isPending ? t("common.loading") : t("auth.loginButton") }}
          </Button>
        </form>
      </AdminCard>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import AdminBrandMark from "../components/AdminBrandMark.vue";
import AdminCard from "../components/AdminCard.vue";
import { useAuth } from "../lib/auth";
import { t } from "../lib/i18n";

/**
 * Admin sign-in.
 *
 * Two failure modes, two messages: a rejected credential is an authentication
 * result (generic copy, because distinguishing "no such account" from "wrong
 * password" is an enumeration oracle) while an unreachable API is an
 * infrastructure problem. Reporting the second as the first sends an operator
 * hunting for the wrong cause for as long as it takes to find the network tab.
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
  // Only an in-app absolute path is safe: `//host` would leave the console.
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return "/";
  return value;
});

async function submit(): Promise<void> {
  if (isPending.value) return;
  isPending.value = true;
  errorMessage.value = "";
  try {
    await auth.login(identifier.value.trim(), password.value);
    await router.push(redirectTarget.value);
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError && error.status === 401
        ? t("auth.invalidCredentials")
        : t("admin.apiUnreachable");
  } finally {
    isPending.value = false;
  }
}
</script>
