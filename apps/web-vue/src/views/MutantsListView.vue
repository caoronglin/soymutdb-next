<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import {
  getReleaseId,
  listMutantLines,
  type MutantLineResponse,
} from "@soymutdb/api-client";
import { queryKeys } from "@soymutdb/query-keys";
import { ConfigProvider, Input, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { useSiteContextStore } from "../stores/site-context";

// Public mutant-line browser (Phase F). Lists released mutant lines by public
// identifier (DB-CORE-2): the response carries ONLY public_id, never an internal
// persistence key, and the cache key is scoped by release + site variant
// (DB-CORE-6). The mutagen filter feeds the request + the URL deep link.
const site = useSiteContextStore();

const mutagen = ref<string>("");
const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const lines = computed<MutantLineResponse[]>(() => toValue(query.data) ?? []);

const query = useQuery({
  queryKey: computed(() =>
    queryKeys.mutants.list({
      mutagen: mutagen.value || null,
      limit: 50,
      releaseId: getReleaseId(),
      siteVariant: site.siteVariant,
    }),
  ),
  queryFn: () => listMutantLines({ mutagen: mutagen.value || undefined, limit: 50 }),
  staleTime: 60_000,
});
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="mx-auto max-w-3xl p-8">
      <p class="text-sm opacity-70"><RouterLink to="/" class="underline">Home</RouterLink></p>
      <h1 class="mt-2 text-2xl font-semibold">Mutant Lines</h1>

      <form class="mt-6 flex items-center gap-3" role="search" @submit.prevent>
        <label class="text-sm opacity-70" for="mutagen">Exact mutagen</label>
        <Input
          id="mutagen"
          v-model="mutagen"
          placeholder="e.g. EMS"
          data-testid="mutagen-filter"
        />
      </form>

      <div v-if="isLoading" data-testid="mutants-loading" class="mt-6 grid gap-3">
        <div v-for="index in 4" :key="index" class="h-16 w-full rounded bg-black/5" />
      </div>

      <div v-else-if="isError" data-testid="mutants-error" class="mt-6 rounded border border-red-300 p-5">
        <p class="font-medium">Could not load mutant lines.</p>
      </div>

      <div v-else data-testid="mutants-results" class="mt-6">
        <p v-if="lines.length === 0" data-testid="mutants-empty" class="text-sm opacity-70">
          No public mutant lines<span v-if="mutagen"> for mutagen “{{ mutagen }}”</span>.
        </p>
        <ul v-else class="grid gap-3">
          <li v-for="line in lines" :key="line.public_id">
            <RouterLink
              :to="{ path: `/mutants/${line.public_id}` }"
              data-testid="mutant-row"
              :data-public-id="line.public_id"
              class="flex items-center gap-3 rounded-lg border p-4 transition-colors hover:border-primary"
            >
              <Tag class="font-mono uppercase">mutant</Tag>
              <span class="font-medium">{{ line.name }}</span>
              <span class="ml-auto font-mono text-sm opacity-70">{{ line.public_id }}</span>
            </RouterLink>
          </li>
        </ul>
      </div>
    </div>
  </ConfigProvider>
</template>
