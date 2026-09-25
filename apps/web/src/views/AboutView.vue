<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";

import DOMPurify from "dompurify";

import { getSiteAbout, type SiteAbout } from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
import { useSiteContextStore } from "../stores/site-context";

/**
 * About page — admin-authored content from `GET /site/about`.
 *
 * The HTML is authored server-side and already sanitised there; DOMPurify
 * sanitises again before `v-html` because a public page rendering CMS HTML has
 * no other defence in depth.
 */
const site = useSiteContextStore();

const query = useQuery({
  queryKey: ["site-about", site.siteVariant],
  queryFn: () => getSiteAbout(site.siteVariant),
  staleTime: 60_000,
  retry: false,
});

const about = computed<SiteAbout | undefined>(() => toValue(query.data));
const isPending = computed(() => toValue(query.isPending));
const isError = computed(() => toValue(query.isError));

const title = computed(() => about.value?.title_en ?? t("about.title"));
const summary = computed(() => about.value?.summary_en ?? "");
const content = computed(() => about.value?.content_en ?? "");
const sanitizedContent = computed(() => DOMPurify.sanitize(content.value));
const hasContent = computed(() => Boolean(summary.value.trim() || content.value.trim()));
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-3xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ title }}</h1>

      <p v-if="isPending" data-testid="about-loading" class="mt-6 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <div v-else-if="isError" class="mt-6 rounded-md border border-red-300 p-5" role="alert">
        <p class="font-medium">{{ t("about.loadErrorTitle") }}</p>
        <p class="mt-1 text-sm opacity-70">{{ t("about.loadErrorSubtitle") }}</p>
        <Button class="mt-3" @click="query.refetch()">{{ t("common.retry") }}</Button>
      </div>
      <p v-else-if="!hasContent" data-testid="about-empty" class="mt-6 text-sm opacity-70">
        {{ t("about.empty") }}
      </p>
      <template v-else>
        <p v-if="summary" class="mt-6 text-lg opacity-80">{{ summary }}</p>
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div v-html="sanitizedContent" data-testid="about-content" class="mt-4 leading-relaxed" />
      </template>
    </div>
  </PortalLayout>
</template>
