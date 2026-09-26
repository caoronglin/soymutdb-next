<script setup lang="ts">
import { useRoute } from "vue-router";

import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Explicit landing page for legacy console deep links whose workflow has not
 * been restored in the Vue console.
 *
 * The alternative — a bare 404 or an empty shell — reads as "the feature broke"
 * or, worse, as "there is nothing here", which is why the migration plan
 * forbids both. This page names the requested path, states why the workflow is
 * unavailable in this build, and offers the routes that are restored. It does
 * not pretend to load data and it writes nothing.
 *
 * Route entries may pass `reasonKey`/`statusKey`/`referenceHref` to turn a
 * generic placeholder into a documented disposition; the ADR-0009 retired
 * routes keep the defaults.
 */
withDefaults(
  defineProps<{
    /** i18n key naming why this workflow is unavailable. */
    reasonKey?: string;
    /** i18n key for the status line; defaults to the generic "planned". */
    statusKey?: string;
    /** Optional in-app route the operator can follow. */
    referenceTo?: string;
    /** Optional external reference the operator can follow (ADR/docs URL). */
    referenceHref?: string;
    /** i18n key for the reference link label. */
    referenceLabelKey?: string;
  }>(),
  {
    reasonKey: "",
    statusKey: "admin.legacyUnavailable.planned",
    referenceTo: "",
    referenceHref: "",
    referenceLabelKey: "admin.legacyUnavailable.reference",
  },
);

const route = useRoute();
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="max-w-2xl py-10" data-testid="legacy-unavailable">
      <h1 class="text-xl font-semibold">{{ t("admin.legacyUnavailable.title") }}</h1>
      <p class="mt-2 text-sm opacity-70">{{ t("admin.legacyUnavailable.description") }}</p>
      <p class="mt-3 rounded-md border border-border bg-muted px-3 py-2 font-mono text-xs">
        {{ t("admin.legacyUnavailable.requested") }}: {{ route.path }}
      </p>
      <p v-if="reasonKey" class="mt-3 text-sm" data-testid="legacy-unavailable-reason">
        <span class="opacity-70">{{ t("admin.legacyUnavailable.reason") }}:</span>
        {{ t(reasonKey) }}
      </p>
      <p class="mt-3 text-sm">
        <span class="opacity-70">{{ t("admin.legacyUnavailable.status") }}:</span>
        <span data-testid="legacy-unavailable-status">{{ t(statusKey) }}</span>
      </p>
      <p v-if="referenceTo || referenceHref" class="mt-3 text-sm">
        <RouterLink v-if="referenceTo" :to="referenceTo" class="text-primary underline" data-testid="legacy-unavailable-reference">
          {{ t(referenceLabelKey) }}
        </RouterLink>
        <a
          v-else
          :href="referenceHref"
          target="_blank"
          rel="noopener noreferrer"
          class="text-primary underline"
          data-testid="legacy-unavailable-reference"
        >
          {{ t(referenceLabelKey) }}
        </a>
      </p>
      <div class="mt-5 flex flex-wrap gap-3">
        <RouterLink
          to="/"
          class="inline-flex min-h-10 items-center rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground"
          data-testid="legacy-unavailable-home"
        >
          {{ t("admin.legacyUnavailable.backToDashboard") }}
        </RouterLink>
        <RouterLink
          v-if="route.path.startsWith('/settings')"
          to="/settings"
          class="inline-flex min-h-10 items-center rounded-md border border-border px-3 text-sm"
          data-testid="legacy-unavailable-settings"
        >
          {{ t("admin.settings") }}
        </RouterLink>
        <RouterLink
          v-if="route.path.startsWith('/content')"
          to="/content"
          class="inline-flex min-h-10 items-center rounded-md border border-border px-3 text-sm"
          data-testid="legacy-unavailable-content"
        >
          {{ t("admin.content") }}
        </RouterLink>
        <RouterLink
          v-if="route.path.startsWith('/news')"
          to="/news"
          class="inline-flex min-h-10 items-center rounded-md border border-border px-3 text-sm"
          data-testid="legacy-unavailable-news"
        >
          {{ t("admin.news.title") }}
        </RouterLink>
        <RouterLink
          v-if="route.path.startsWith('/imports')"
          to="/imports"
          class="inline-flex min-h-10 items-center rounded-md border border-border px-3 text-sm"
          data-testid="legacy-unavailable-imports"
        >
          {{ t("admin.imports") }}
        </RouterLink>
      </div>
    </div>
  </ConfigProvider>
</template>
