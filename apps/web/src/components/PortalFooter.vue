<script setup lang="ts">
import { t } from "../lib/i18n";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Portal footer. Carries provenance (release, site variant), the primary
 * resource links and the version/API entry, mirroring the React site footer.
 * It must never displace the database workflow, so it stays one compact band.
 */
const site = useSiteContextStore();
const year = new Date().getFullYear();

const FOOTER_LINKS = [
  { to: "/genes", labelKey: "nav.genes" },
  { to: "/variants", labelKey: "nav.variants" },
  { to: "/browser", labelKey: "nav.browser" },
  { to: "/blast", labelKey: "nav.blast" },
  { to: "/tools", labelKey: "nav.tools" },
  { to: "/downloads", labelKey: "nav.downloads" },
  { to: "/guide", labelKey: "nav.guide" },
  { to: "/news", labelKey: "nav.news" },
  { to: "/seed-request", labelKey: "nav.seedRequest" },
  { to: "/publications", labelKey: "nav.publications" },
  { to: "/about", labelKey: "nav.about" },
  { to: "/help", labelKey: "nav.help" },
] as const;
</script>

<template>
  <footer class="mt-16 border-t border-border/80 bg-muted/20">
    <div class="mx-auto max-w-7xl px-4 py-8">
      <p class="text-xs text-muted-foreground" data-testid="portal-footer-context">
        SoyMutDB · {{ site.siteVariant }} · {{ t("releases.title") }}:
        {{ site.releaseId ?? t("releases.active") }}
      </p>

      <nav class="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-sm" :aria-label="t('footer.label')">
        <RouterLink
          v-for="link in FOOTER_LINKS"
          :key="link.to"
          :to="link.to"
          class="site-footer-link text-muted-foreground outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring"
        >
          {{ t(link.labelKey) }}
        </RouterLink>
      </nav>

      <div class="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-4 text-sm text-muted-foreground">
        <p>{{ t("footer.copyright", { year }) }}</p>
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span class="font-mono text-xs">{{ t("footer.version") }}</span>
          <RouterLink to="/about" class="site-footer-link outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring">
            {{ t("footer.about") }}
          </RouterLink>
          <RouterLink to="/tools/api" class="site-footer-link outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring">
            {{ t("footer.api") }}
          </RouterLink>
        </div>
      </div>
    </div>
  </footer>
</template>
