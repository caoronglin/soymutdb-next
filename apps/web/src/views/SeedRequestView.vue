<script setup lang="ts">
import { ref } from "vue";

import { authRequest } from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";

/**
 * Seed request — the physical-material request form.
 *
 * The request is submitted through the shared authenticated transport, so the
 * release/site context and the CSRF/refresh plumbing are identical to every
 * other mutating call. This route is intentionally last in the portal: the
 * database record is the primary product, the request form only follows it.
 */
const form = ref({
  name: "",
  email: "",
  institution: "",
  mutant_lines: "",
  purpose: "",
});
const isPending = ref(false);
const status = ref<"idle" | "sent" | "error">("idle");

async function submit() {
  isPending.value = true;
  status.value = "idle";
  try {
    await authRequest("/seed-requests", { method: "POST", json: { ...form.value } });
    status.value = "sent";
  } catch {
    status.value = "error";
  } finally {
    isPending.value = false;
  }
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-2xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("seedRequest.title") }}</h1>
      <p class="mt-1 text-sm opacity-70">{{ t("seedRequest.subtitle") }}</p>

      <form class="mt-6 grid gap-4" @submit.prevent="submit">
        <label class="text-sm opacity-70">
          {{ t("seedRequest.name") }}
          <input v-model="form.name" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" data-testid="seed-request-name" />
        </label>
        <label class="text-sm opacity-70">
          {{ t("seedRequest.email") }}
          <input v-model="form.email" type="email" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" data-testid="seed-request-email" />
        </label>
        <label class="text-sm opacity-70">
          {{ t("seedRequest.institution") }}
          <input v-model="form.institution" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" />
        </label>
        <label class="text-sm opacity-70">
          {{ t("seedRequest.mutantLines") }}
          <textarea
            v-model="form.mutant_lines"
            rows="3"
            class="mt-1 w-full rounded-md border bg-background p-2 font-mono text-sm"
            data-testid="seed-request-lines"
          />
        </label>
        <label class="text-sm opacity-70">
          {{ t("seedRequest.purpose") }}
          <textarea v-model="form.purpose" rows="4" class="mt-1 w-full rounded-md border bg-background p-2 text-sm" />
        </label>

        <p v-if="status === 'error'" class="text-sm text-red-700" role="alert" data-testid="seed-request-error">
          {{ t("seedRequest.submitFailed") }}
        </p>
        <p v-else-if="status === 'sent'" class="text-sm text-green-700" role="status" data-testid="seed-request-success">
          {{ t("seedRequest.success") }}
        </p>

        <Button html-type="submit" :disabled="isPending" data-testid="seed-request-submit">
          {{ isPending ? t("common.loading") : t("seedRequest.submit") }}
        </Button>
      </form>
    </div>
  </PortalLayout>
</template>
