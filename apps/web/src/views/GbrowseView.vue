<script setup lang="ts">
import { computed, ref, toValue, watch } from "vue";
import { useRouter } from "vue-router";

import { useQuery } from "@tanstack/vue-query";

import type { AssemblyInfo } from "@soymutdb/api-client";
import { jbrowseUrl } from "@soymutdb/shared/genomics";
import { Button } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
import { assembliesQueryOptions } from "../lib/query-options";

/**
 * JBrowse transfer page: pick the assembly, then open the canonical browser
 * route (which owns the JBrowse origin and the bridge) in a new tab. Keeping
 * this indirection means the assembly decision stays inside the portal.
 */
const DEFAULT_LOCUS = "chr01";

const router = useRouter();
const assembliesQuery = useQuery(assembliesQueryOptions());
const assemblies = computed<AssemblyInfo[]>(() => toValue(assembliesQuery.data) ?? []);
const draftAssemblyId = ref("");

const defaultAssembly = computed(
  () => assemblies.value.find((item) => item.is_default) ?? assemblies.value[0],
);
const selectedAssembly = computed(
  () =>
    assemblies.value.find((item) => String(item.id) === draftAssemblyId.value) ??
    defaultAssembly.value,
);

watch(
  defaultAssembly,
  (assembly) => {
    if (!draftAssemblyId.value && assembly) draftAssemblyId.value = String(assembly.id);
  },
  { immediate: true },
);

function openBrowser() {
  if (!selectedAssembly.value) return;
  const target = router.resolve(
    jbrowseUrl({ chromosome: DEFAULT_LOCUS }, selectedAssembly.value.name),
  );
  window.open(target.href, "_blank", "noopener");
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-3xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("search.gbrowse.title") }}</h1>
      <p class="mt-1 max-w-2xl text-sm opacity-70">{{ t("search.gbrowse.desc") }}</p>

      <form class="mt-6 grid max-w-sm gap-4" @submit.prevent="openBrowser">
        <label class="text-sm opacity-70">
          {{ t("search.gbrowse.assembly") }}
          <select
            v-model="draftAssemblyId"
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            data-testid="gbrowse-assembly"
          >
            <option v-for="item in assemblies" :key="String(item.id)" :value="String(item.id)">
              {{ item.name }}{{ item.is_default ? " · default" : "" }}
            </option>
          </select>
        </label>
        <Button html-type="submit" :disabled="!selectedAssembly" data-testid="gbrowse-open">
          {{ t("search.gbrowse.open") }}
        </Button>
      </form>
    </div>
  </PortalLayout>
</template>
