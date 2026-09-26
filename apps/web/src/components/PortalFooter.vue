<script setup lang="ts">
import { t } from "../lib/i18n";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Portal footer. Kept deliberately short: the footer must never displace the
 * database workflow, so it carries provenance (release, site variant) and the
 * resource links rather than marketing copy.
 */
const site = useSiteContextStore();
const year = new Date().getFullYear();
</script>

<template>
  <footer class="mt-16 border-t py-8 text-sm opacity-70">
    <div class="mx-auto flex max-w-7xl flex-col gap-2 px-4">
      <p data-testid="portal-footer-context">
        SoyMutDB · {{ site.siteVariant }} · {{ t("releases.title") }}:
        {{ site.releaseId ?? t("releases.active") }}
      </p>
      <nav class="flex flex-wrap gap-4" :aria-label="t('footer.label')">
        <RouterLink to="/about" class="underline">{{ t("nav.about") }}</RouterLink>
        <RouterLink to="/help" class="underline">{{ t("nav.help") }}</RouterLink>
        <RouterLink to="/publications" class="underline">{{ t("nav.publications") }}</RouterLink>
        <RouterLink to="/tools/api" class="underline">{{ t("nav.contact") }}</RouterLink>
      </nav>
      <p>© {{ year }} SoyMutDB</p>
    </div>
  </footer>
</template>
