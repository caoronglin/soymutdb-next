<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  getReleaseId,
  globalSearch,
  type FederatedSearchResponse,
  type SearchResponse,
  type SearchResult,
  type SearchResultType,
} from "@soymutdb/api-client";
import { queryKeys } from "@soymutdb/query-keys";
import { ConfigProvider, Input, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { useSiteContextStore } from "../stores/site-context";

// Public omnibox search (Phase F). Ported from the React route, preserving the
// contract: URL search-state deep links, the assembly/release/site-variant
// scoped cache key (DB-CORE-6), public-identifier-only results (DB-CORE-2), and
// disabled rows for hits without a canonical URL (never a fake "#" link).
const EXTERNAL_SOURCES = ["ncbi", "uniprot", "ensembl", "ebi"] as const;

const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();

const q = computed(() => (route.query.q ? String(route.query.q) : ""));
const types = computed<SearchResultType[] | undefined>(() =>
  Array.isArray(route.query.types)
    ? (route.query.types.map(String) as SearchResultType[])
    : undefined,
);
const cursor = computed(() => (route.query.cursor ? String(route.query.cursor) : undefined));
const assembly = computed(() => (route.query.assembly ? String(route.query.assembly) : undefined));
const external = computed(
  () => route.query.external === "1" || route.query.external === "true",
);
const resultLimit = computed(() => (route.query.limit ? Number(route.query.limit) : 20));
const enabled = computed(() => Boolean(q.value.trim()));

const input = ref(q.value);
const externalInput = ref(external.value);
watch(q, (value) => (input.value = value));
watch(external, (value) => (externalInput.value = value));

const query = useQuery({
  queryKey: computed(() =>
    queryKeys.search.global({
      query: q.value || undefined,
      types: types.value,
      cursor: cursor.value,
      limit: resultLimit.value,
      assemblyId: assembly.value,
      releaseId: getReleaseId(),
      siteVariant: site.siteVariant,
      federated: external.value,
    }),
  ),
  queryFn: () =>
    globalSearch({
      q: q.value!,
      types: types.value,
      cursor: cursor.value,
      limit: resultLimit.value,
      assembly_id: assembly.value ? Number(assembly.value) : undefined,
      sources: external.value ? [...EXTERNAL_SOURCES] : undefined,
    }),
  enabled,
  staleTime: 60_000,
});

// vue-query v5 returns a reactive object whose fields are nested refs; the
// template does not auto-unwrap those, so expose explicit (top-level) computeds.
const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const errorRequestId = computed(
  () => (toValue(query.error) as { request_id?: string } | null)?.request_id ?? "unavailable",
);
const searchData = computed<
  SearchResponse | FederatedSearchResponse | undefined
>(() => toValue(query.data));

const results = computed<SearchResult[]>(() =>
  searchData.value && "results" in searchData.value ? searchData.value.results : [],
);
const totalCount = computed<number | null>(() =>
  searchData.value && "results" in searchData.value ? searchData.value.total_count : null,
);
const federated = computed<FederatedSearchResponse | undefined>(() =>
  searchData.value && "sources" in searchData.value ? searchData.value : undefined,
);

const retry = () => query.refetch();

function submit() {
  const next = input.value.trim();
  void router.push({
    path: "/search",
    query: {
      q: next || undefined,
      external: next && externalInput.value ? "1" : undefined,
      limit: next ? String(20) : undefined,
    },
  });
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="mx-auto max-w-3xl p-8">
      <p class="text-sm opacity-70">Search</p>
      <h1 class="mt-2 text-4xl font-semibold tracking-tight">Discover SoyMutDB</h1>
      <p class="mt-3 text-sm opacity-70">
        Search genes, variants, mutant lines, publications, and connected external sources.
      </p>

      <form class="mt-10 space-y-3" role="search" @submit.prevent="submit">
        <Input
          v-model="input"
          type="search"
          role="searchbox"
          aria-label="Search"
          placeholder="Search genes, variants, publications…"
          data-testid="search-input"
        />
        <label class="inline-flex cursor-pointer items-center gap-2 text-sm opacity-70">
          <input
            v-model="externalInput"
            data-testid="external-source-toggle"
            type="checkbox"
          />
          Search external sources (NCBI · UniProt · Ensembl · EBI)
        </label>
        <button type="submit" class="rounded-md border px-3 py-2 text-sm" data-testid="search-submit">
          Search
        </button>
      </form>

      <div v-if="!q" class="mt-12 text-sm opacity-70" data-testid="search-empty-prompt">
        Enter a gene, variant, or publication to explore the database.
      </div>

      <div v-else-if="isError" class="mt-10 rounded border border-red-300 p-5" data-testid="search-error">
        <p class="font-medium">Search failed</p>
        <p class="text-sm opacity-70">Request ID: {{ errorRequestId }}</p>
        <button type="button" class="mt-2 rounded-md border px-3 py-2 text-sm" @click="retry">
          Retry
        </button>
      </div>

      <div v-else-if="isLoading && !searchData" class="mt-10 grid gap-3" data-testid="search-loading">
        <div v-for="index in 5" :key="index" class="h-20 w-full rounded bg-black/5" />
      </div>

      <template v-else-if="federated">
        <section data-testid="search-results" class="mt-10" aria-label="External search results">
          <div class="mb-4 text-sm opacity-70">
            External results for <span class="font-mono">“{{ q }}”</span>
          </div>
          <div class="grid gap-6">
            <div v-for="source in federated.sources" :key="source.source">
              <div class="mb-2 flex items-center gap-2">
                <h2 class="font-semibold uppercase">{{ source.source }}</h2>
                <Tag>{{ source.status }}</Tag>
              </div>
              <p v-for="(hit, index) in source.hits" :key="`${hit.id ?? hit.title}-${index}`">
                <a
                  :href="hit.url"
                  :data-testid="hit.url ? 'search-result-row' : 'search-result-disabled'"
                  :data-url="hit.url"
                  :aria-disabled="!hit.url"
                  class="flex items-center gap-3 rounded-lg border p-4"
                >
                  <span class="font-medium">{{ hit.title }}</span>
                </a>
              </p>
              <p v-if="source.hits.length === 0" class="text-sm opacity-70">No results from this source.</p>
            </div>
          </div>
        </section>
      </template>

      <section v-else data-testid="search-results" class="mt-10" aria-label="Search results">
        <div class="mb-4 flex items-center justify-between text-sm opacity-70">
          <span>Results for <span class="font-mono">“{{ q }}”</span></span>
          <span v-if="totalCount !== null">{{ totalCount }} results</span>
        </div>
        <p v-if="results.length === 0" data-testid="search-no-matches" class="text-sm opacity-70">
          No records matched this query.
        </p>
        <ul v-else class="grid gap-3">
          <li v-for="result in results" :key="`${result.type}-${result.id}`">
            <a
              v-if="result.url"
              :href="result.url"
              data-testid="search-result-row"
              :data-url="result.url"
              class="flex items-center gap-3 rounded-lg border p-4 transition-colors hover:border-primary"
            >
              <Tag class="font-mono uppercase">{{ result.type }}</Tag>
              <span class="min-w-0 flex-1 truncate font-medium">{{ result.name ?? result.id }}</span>
            </a>
            <div
              v-else
              data-testid="search-result-disabled"
              class="flex items-center gap-3 rounded-lg border p-4 opacity-60"
            >
              <Tag class="font-mono uppercase">{{ result.type }}</Tag>
              <span class="min-w-0 flex-1 truncate font-medium">{{ result.name ?? result.id }}</span>
            </div>
          </li>
        </ul>
      </section>
    </div>
  </ConfigProvider>
</template>
