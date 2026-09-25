<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { setAccessToken, authRequest } from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { normalizeBasePath } from "../lib/base-path";
import { t } from "../lib/i18n";

/**
 * Login — internal-site researcher authentication.
 *
 * The form posts through the shared api-client so the CSRF/refresh plumbing and
 * the auth-logout event stream stay identical to the admin console. The access
 * token is kept in module memory (never storage), exactly like the admin.
 *
 * `?redirect=` is honoured but whitelisted to a same-site path: a protocol,
 * scheme-relative (`//host`), backslash or absolute URL is dropped rather than
 * followed, because an open redirect turns a login page into a credential
 * relay. The default destination is the portal root, never an internal-only
 * route.
 */
interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

const route = useRoute();
const router = useRouter();

const email = ref("");
const password = ref("");
const errorMessage = ref("");
const isPending = ref(false);

/** Whitelist the post-login destination to a same-site path. */
function safeRedirect(value: unknown): string {
  if (typeof value !== "string" || !value) return "/";
  if (
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    /^[a-z][a-z0-9+.-]*:/i.test(value)
  ) {
    return "/";
  }
  return value;
}

const redirectTarget = safeRedirect(route.query.redirect);

async function submit() {
  if (isPending.value) return;
  isPending.value = true;
  errorMessage.value = "";
  try {
    const response = await authRequest<LoginResponse>("/auth/login", {
      method: "POST",
      json: { email: email.value.trim(), password: password.value },
    });
    setAccessToken(response.access_token);
    await router.push(normalizeBasePath(import.meta.env.BASE_URL).slice(0, -1) + redirectTarget);
  } catch {
    // Never echo the server's reason: a distinct message for "no such user" is
    // an account-existence oracle.
    errorMessage.value = t("auth.invalidCredentials");
  } finally {
    isPending.value = false;
  }
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-sm px-4 py-12">
      <h1 class="text-2xl font-semibold">{{ t("loginPage.title") }}</h1>
      <p class="mt-1 text-sm opacity-70">{{ t("loginPage.subtitle") }}</p>

      <form class="mt-6 grid gap-4" @submit.prevent="submit">
        <label class="text-sm opacity-70">
          {{ t("auth.email") }}
          <input
            v-model="email"
            type="email"
            autocomplete="username"
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            data-testid="login-email"
          />
        </label>
        <label class="text-sm opacity-70">
          {{ t("auth.password") }}
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            data-testid="login-password"
          />
        </label>
        <p v-if="errorMessage" class="text-sm text-red-700" role="alert" data-testid="login-error">
          {{ errorMessage }}
        </p>
        <Button html-type="submit" :disabled="isPending" data-testid="login-submit">
          {{ isPending ? t("common.loading") : t("auth.loginButton") }}
        </Button>
      </form>
    </div>
  </PortalLayout>
</template>
