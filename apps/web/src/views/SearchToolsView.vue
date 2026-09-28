<script setup lang="ts">
/**
 * Search tools catalog — the /search hub's entry cards for the standalone
 * research tools. Links only; each tool owns its own assembly-scoped request.
 */
import { Button } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";

const TOOLS = [
  { to: "/tools/seqfetch", titleKey: "search.tools.seqfetch", descKey: "search.tools.seqfetchDesc" },
  { to: "/tools/enrichment", titleKey: "search.tools.enrichment", descKey: "search.tools.enrichmentDesc" },
  { to: "/tools/exppattern", titleKey: "search.tools.exppattern", descKey: "search.tools.exppatternDesc" },
] as const;
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-5xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("search.tools.title") }}</h1>
      <p class="mt-1 max-w-2xl text-sm opacity-70">{{ t("search.tools.desc") }}</p>

      <ul class="mt-6 grid gap-4 md:grid-cols-3">
        <li v-for="tool in TOOLS" :key="tool.to">
          <RouterLink
            :to="tool.to"
            class="block rounded-lg border p-5 transition hover:bg-black/5"
            :data-testid="'search-tool-' + tool.to.split('/').pop()"
          >
            <h2 class="font-medium">{{ t(tool.titleKey) }}</h2>
            <p class="mt-1 text-sm opacity-70">{{ t(tool.descKey) }}</p>
            <span class="mt-3 inline-block text-sm underline">{{ t("search.tools.open") }}</span>
          </RouterLink>
        </li>
      </ul>

      <div class="mt-8">
        <!--
          Route through the assembly picker instead of deep-linking JBrowse
          with a bare locus: /browser requires an explicit assembly + release,
          so a context-free link now renders "context unavailable" rather than
          silently opening the v4 namespace.
        -->
        <Button data-testid="search-tools-gbrowse" @click="$router.push('/search/gbrowse')">
          {{ t("search.gbrowse.open") }}
        </Button>
      </div>
    </div>
  </PortalLayout>
</template>
