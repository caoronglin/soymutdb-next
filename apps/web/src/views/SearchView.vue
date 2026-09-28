<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  type FederatedSearchResponse,
  type InternalSearchResponse,
  type SearchResponse,
  type SearchResult,
  type SearchResultType,
  internalSearch,
} from "@soymutdb/api-client";
import { Button, Input, Tag } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import AppIcon from "../components/table/AppIcon.vue";
import PageHeader from "../components/table/PageHeader.vue";
import type { IconName } from "../components/table/table-types";
import StateBlock from "../components/states/StateBlock.vue";
import { t } from "../lib/i18n";
import { globalSearchQueryOptions } from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

// Public omnibox search (Phase F). Ported from the React route, preserving the
// contract: URL search-state deep links, the assembly/release/site-variant
// scoped cache key (DB-CORE-6), public-identifier-only results (DB-CORE-2), and
// disabled rows for hits without a canonical URL (never a fake "#" link).
const EXTERNAL_SOURCES = ["ncbi", "uniprot", "ensembl", "ebi"] as const;

/** Leading glyph per entity type; unknown types fall back to a document. */
const RESULT_ICONS: Record<string, IconName> = {
  gene: "dna",
  variant: "dna",
  mutant_line: "beaker",
};

function resultIcon(type: string): IconName {
  return RESULT_ICONS[type] ?? "file-text";
}

const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();

const q = computed(() => (route.query.q ? String(route.query.q) : ""));
const types = computed<SearchResultType[] | undefined>(() =>
  Array.isArray(route.query.types)
    ? (route.query.types.map(String) as SearchResultType[])
    : undefined,
);
const routeCursor = computed(() => (route.query.cursor ? String(route.query.cursor) : undefined));
// Cursor stack: Next pushes the returned cursor, Previous pops. Any change to
// the query identity resets to page one because the old cursor no longer
// applies to the new filter set.
const cursorStack = ref<Array<string | undefined>>([routeCursor.value]);
const cursor = computed(() => cursorStack.value[cursorStack.value.length - 1]);
const assembly = computed(() => (route.query.assembly ? String(route.query.assembly) : undefined));
const external = computed(
  () => route.query.external === "1" || route.query.external === "true",
);
const resultLimit = computed(() => (route.query.limit ? Number(route.query.limit) : 20));
watch([q, types, assembly, resultLimit, external], () => {
  cursorStack.value = [undefined];
});

const input = ref(q.value);
const externalInput = ref(external.value);
watch(q, (value) => (input.value = value));
watch(external, (value) => (externalInput.value = value));

const query = useQuery(
  computed(() =>
    globalSearchQueryOptions({
      query: q.value || undefined,
      types: types.value,
      cursor: cursor.value,
      limit: resultLimit.value,
      assemblyId: assembly.value,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
      federated: external.value,
      sources: EXTERNAL_SOURCES,
    }),
  ),
);

// OPT-05: internal-site search hits the authorized `/search/internal` endpoint,
// which is the ONLY source of the private `internal_id`. It runs independently
// of the public path so an external site is byte-for-byte unchanged, and it is
// keyed by the same release/site context so the two can never drift.
const internalQuery = useQuery(
  computed(() => ({
    queryKey: [
      "search-internal",
      q.value,
      resultLimit.value,
      site.releaseId,
      site.siteVariant,
    ] as const,
    queryFn: () => internalSearch(q.value, { limit: resultLimit.value }),
    enabled: site.isInternal && Boolean(q.value.trim()),
    staleTime: 30_000,
  })),
);
const internalData = computed<InternalSearchResponse | undefined>(() =>
  toValue(internalQuery.data),
);

interface InternalRow {
  publicId: string;
  internalId: string;
  name: string;
  type: string;
  url?: string | null;
  matchedField: string;
}

// Normalize the two entity shapes (mutant `public_id` / gene `gene_id`) into one
// renderable row so a binding swap flips every assertion below.
const internalRows = computed<InternalRow[]>(() => {
  const data = internalData.value;
  if (!data) return [];
  const rows: InternalRow[] = [];
  for (const mutant of data.mutants ?? []) {
    rows.push({
      publicId: mutant.public_id,
      internalId: mutant.internal_id,
      name: mutant.name,
      type: mutant.entity_type,
      url: mutant.url,
      matchedField: mutant.matched_field,
    });
  }
  for (const gene of data.genes ?? []) {
    rows.push({
      publicId: gene.gene_id,
      internalId: gene.internal_id,
      name: gene.name ?? gene.gene_id,
      type: gene.entity_type,
      url: gene.url,
      matchedField: gene.matched_field,
    });
  }
  return rows;
});

// Copy affordance per id. `navigator.clipboard` is absent in jsdom and can be
// denied in insecure contexts, so it falls back to a hidden textarea and never
// throws into the render path.
const copiedId = ref<string | null>(null);

async function copyId(value: string): Promise<void> {
  copiedId.value = value;
  try {
    const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : undefined;
    if (clipboard?.writeText) {
      await clipboard.writeText(value);
      return;
    }
  } catch {
    /* permission denied / no secure context — use the DOM fallback */
  }
  legacyCopy(value);
}

function legacyCopy(value: string): void {
  try {
    if (typeof document === "undefined") return;
    const el = document.createElement("textarea");
    el.value = value;
    el.setAttribute("readonly", "");
    el.style.position = "absolute";
    el.style.left = "-9999px";
    document.body.appendChild(el);
    el.select();
    try {
      document.execCommand("copy");
    } catch {
      /* best effort — the value stays selectable on screen */
    }
    document.body.removeChild(el);
  } catch {
    /* clipboard is best-effort; never break the row */
  }
}

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

// P1-05: the internal search response carries a cursor; without controls the
// next page was unreachable even though has_more/next_cursor were returned.
const nextCursor = computed<string | null>(() =>
  searchData.value && "results" in searchData.value ? searchData.value.next_cursor : null,
);
const hasMore = computed<boolean>(() =>
  searchData.value && "results" in searchData.value
    ? Boolean(searchData.value.has_more)
    : false,
);
const canPrevious = computed(() => cursorStack.value.length > 1);
const canNext = computed(() => hasMore.value && Boolean(nextCursor.value));

// DB-CORE assembly contract: an unscoped query that matches several genome
// versions is reported as ambiguous over the FULL result set (not the page),
// and hits are grouped per assembly so no version is silently collapsed.
const ambiguous = computed<boolean>(() =>
  searchData.value && "results" in searchData.value
    ? Boolean(searchData.value.ambiguous)
    : false,
);

const resultGroups = computed<Array<{ label: string; items: SearchResult[] }>>(() => {
  const items = results.value;
  if (!ambiguous.value) return [{ label: "", items }];
  const groups = new Map<string, SearchResult[]>();
  for (const result of items) {
    const label =
      result.assembly ??
      (result.assembly_id != null
        ? String(result.assembly_id)
        : t("search.unknownAssembly"));
    const bucket = groups.get(label);
    if (bucket) bucket.push(result);
    else groups.set(label, [result]);
  }
  return [...groups.entries()].map(([label, groupItems]) => ({ label, items: groupItems }));
});

function retry() {
  void query.refetch();
}

function nextPage(): void {
  const next = nextCursor.value;
  if (!next) return;
  cursorStack.value = [...cursorStack.value, next];
  void router.replace({ path: route.path, query: { ...route.query, cursor: next } });
}

function previousPage(): void {
  if (cursorStack.value.length <= 1) return;
  cursorStack.value = cursorStack.value.slice(0, -1);
  const next = { ...route.query } as Record<string, string>;
  if (cursor.value) next.cursor = cursor.value;
  else delete next.cursor;
  void router.replace({ path: route.path, query: next });
}

/** Map a source status code to a dictionary label; unknown codes stay visible. */
function sourceStatusLabel(status: string): string {
  const keys: Record<string, string> = {
    ok: "search.sourceStatusOK",
    empty: "search.sourceStatusEmpty",
    timeout: "search.sourceStatusTimeout",
    error: "search.sourceStatusError",
    circuit_open: "search.sourceStatusCircuitOpen",
    rate_limited: "search.sourceStatusRateLimited",
  };
  const key = keys[status];
  if (key) return t(key);
  return `${t("search.sourceUnknown")}: ${status}`;
}

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
  <PortalLayout>
    <div class="container-prose py-10 md:py-14">
      <PageHeader
        :eyebrow="t('search.title')"
        :title="t('nav.search')"
        :description="t('search.subtitle')"
      />

      <form class="mt-8 max-w-2xl space-y-3" role="search" @submit.prevent="submit">
        <div class="relative">
          <AppIcon
            name="search"
            class="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            v-model:value="input"
            type="search"
            role="searchbox"
            class="h-12 pl-12"
            :aria-label="t('search.title')"
            :placeholder="t('search.placeholder')"
            data-testid="search-input"
          />
        </div>
        <label class="inline-flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
          <input
            v-model="externalInput"
            data-testid="external-source-toggle"
            type="checkbox"
          />
          <AppIcon name="globe" class="size-4" />
          {{ t("search.externalSources") }}
        </label>
        <Button type="primary" html-type="submit" data-testid="search-submit">
          {{ t("search.location.submit") }}
        </Button>
      </form>

      <!-- Internal site only: authorized result set with BOTH identities and a
           copy control per id (OPT-05). Standalone from the public chain below
           so the external path is unchanged. -->
      <section
        v-if="site.isInternal && q && internalRows.length > 0"
        data-testid="search-internal-results"
        class="mt-10"
        :aria-label="t('search.internalResults')"
      >
        <div class="mb-4 text-sm text-muted-foreground">
          {{ t("nav.internalBadge") }} · <span class="font-mono">“{{ q }}”</span>
        </div>
        <ul class="grid gap-3">
          <li v-for="row in internalRows" :key="`${row.type}-${row.internalId}`">
            <div data-testid="search-internal-row" class="rounded-xl border bg-card p-4 shadow-sm">
              <div class="flex flex-wrap items-center gap-3">
                <span
                  class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground"
                >
                  <AppIcon :name="resultIcon(row.type)" class="size-4" />
                </span>
                <Tag class="font-mono uppercase">{{ row.type }}</Tag>
                <a v-if="row.url" :href="row.url" class="link-underline font-medium text-primary">{{ row.name }}</a>
                <span v-else class="font-medium">{{ row.name }}</span>
                <span class="text-xs text-muted-foreground">
                  {{ t("search.matchedField") }}:
                  <span class="font-mono">{{ row.matchedField }}</span>
                </span>
              </div>
              <div class="mt-3 grid gap-1 text-xs">
                <div class="flex items-center gap-2">
                  <span class="text-muted-foreground">public_id</span>
                  <span
                    class="font-mono"
                    data-testid="internal-public-id"
                    :data-id-value="row.publicId"
                  >{{ row.publicId }}</span>
                  <button
                    type="button"
                    class="inline-flex items-center gap-1 rounded border border-border px-2 py-1 transition-colors hover:bg-accent"
                    data-testid="copy-public-id"
                    :data-copy-value="row.publicId"
                    @click="copyId(row.publicId)"
                  >
                    <AppIcon :name="copiedId === row.publicId ? 'check' : 'copy'" class="size-3" />
                    {{ copiedId === row.publicId ? "copied" : "copy" }}
                  </button>
                </div>
                <div class="flex items-center gap-2">
                  <span class="text-muted-foreground">internal_id</span>
                  <span
                    class="font-mono"
                    data-testid="internal-internal-id"
                    :data-id-value="row.internalId"
                  >{{ row.internalId }}</span>
                  <button
                    type="button"
                    class="inline-flex items-center gap-1 rounded border border-border px-2 py-1 transition-colors hover:bg-accent"
                    data-testid="copy-internal-id"
                    :data-copy-value="row.internalId"
                    @click="copyId(row.internalId)"
                  >
                    <AppIcon :name="copiedId === row.internalId ? 'check' : 'copy'" class="size-3" />
                    {{ copiedId === row.internalId ? "copied" : "copy" }}
                  </button>
                </div>
              </div>
            </div>
          </li>
        </ul>
      </section>

      <StateBlock
        v-if="!q"
        data-testid="search-empty-prompt"
        class="mt-12"
        variant="empty"
        icon="search"
        :title="t('search.enterQuery')"
      />

      <StateBlock
        v-else-if="isError"
        data-testid="search-error"
        variant="error"
        class="mt-10"
        :title="t('search.searchFailed')"
        :description="`${t('search.requestId')}: ${errorRequestId}`"
      >
        <template #action>
          <Button data-testid="search-retry" @click="retry">{{ t("common.retry") }}</Button>
        </template>
      </StateBlock>

      <StateBlock
        v-else-if="isLoading && !searchData"
        data-testid="search-loading"
        variant="loading"
        class="mt-10"
        :title="t('search.searching')"
        :rows="5"
      />

      <template v-else-if="federated">
        <section data-testid="search-results" class="mt-10" :aria-label="t('search.externalResultsSection')">
          <div class="mb-4 text-sm text-muted-foreground">
            {{ t("search.externalResultsFor") }} <span class="font-mono">“{{ q }}”</span>
          </div>
          <div class="grid gap-6">
            <div v-for="source in federated.sources" :key="source.source">
              <div class="mb-2 flex items-center gap-2">
                <h2 class="font-semibold uppercase">{{ source.source }}</h2>
                <Tag>{{ sourceStatusLabel(source.status) }}</Tag>
              </div>
              <p v-for="(hit, index) in source.hits" :key="`${hit.id ?? hit.title}-${index}`">
                <a
                  :href="hit.url"
                  :data-testid="hit.url ? 'search-result-row' : 'search-result-disabled'"
                  :data-url="hit.url"
                  :aria-disabled="!hit.url"
                  :tabindex="hit.url ? undefined : -1"
                  class="flex items-center gap-3 rounded-xl border bg-card p-4 shadow-sm"
                  :class="{ 'cursor-not-allowed opacity-60': !hit.url }"
                >
                  <span
                    class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"
                  >
                    <AppIcon name="external" class="size-4" />
                  </span>
                  <span class="min-w-0 flex-1 truncate font-medium">{{ hit.title }}</span>
                  <AppIcon name="arrow-right" class="size-4 shrink-0 text-muted-foreground" />
                </a>
              </p>
              <p v-if="source.hits.length === 0" class="text-sm text-muted-foreground">
                {{ t("search.sourceEmpty") }}
              </p>
            </div>
          </div>
        </section>
      </template>

      <section v-else data-testid="search-results" class="mt-10" :aria-label="t('search.resultsSection')">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
          <span>{{ t("search.resultsFor") }} <span class="font-mono">“{{ q }}”</span></span>
          <span v-if="totalCount !== null">{{ t("search.resultCount", { count: totalCount }) }}</span>
        </div>
        <StateBlock
          v-if="results.length === 0"
          data-testid="search-no-matches"
          variant="empty"
          icon="search"
          :title="t('search.noResults')"
        />
        <div v-else class="grid gap-6">
          <p
            v-if="ambiguous"
            data-testid="search-ambiguous-notice"
            class="flex items-start gap-2 rounded-xl border border-impact-moderate/40 bg-impact-moderate/10 p-3 text-sm"
          >
            <AppIcon name="alert" class="mt-0.5 size-4" />
            <span>{{ t("search.ambiguousNotice") }}</span>
          </p>
          <div v-for="group in resultGroups" :key="group.label || 'all'">
            <h3
              v-if="group.label"
              data-testid="search-assembly-group"
              class="mb-2 text-sm font-semibold"
            >
              {{ t("search.assemblyLabel") }}:
              <span class="font-mono">{{ group.label }}</span>
            </h3>
            <ul class="grid gap-3">
              <li v-for="result in group.items" :key="`${result.type}-${result.id}`">
                <a
                  v-if="result.url"
                  :href="result.url"
                  data-testid="search-result-row"
                  :data-url="result.url"
                  class="flex items-center gap-3 rounded-xl border bg-card p-4 shadow-sm transition-colors hover:border-primary"
                >
                  <span
                    class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground"
                  >
                    <AppIcon :name="resultIcon(result.type)" class="size-4" />
                  </span>
                  <Tag class="font-mono uppercase">{{ result.type }}</Tag>
                  <span class="min-w-0 flex-1 truncate font-medium">{{ result.name ?? result.public_id ?? result.id }}</span>
                  <!-- OPT-06: optional, defensive. An older payload omits both. -->
                  <Tag
                    v-if="result.match_type"
                    data-testid="search-result-match-type"
                    class="shrink-0 font-mono text-xs"
                  >{{ result.match_type }}</Tag>
                  <span
                    v-if="result.cross_version?.length"
                    data-testid="search-cross-version"
                    class="shrink-0 text-xs opacity-60"
                  >{{ result.cross_version.map((link) => link.gene_accession).join(", ") }}</span>
                  <span
                    class="shrink-0 font-mono text-xs opacity-70"
                    data-testid="search-result-public-id"
                  >{{ result.public_id ?? result.id }}</span>
                  <span
                    v-if="site.isInternal && result.internal_id"
                    class="shrink-0 font-mono text-xs opacity-60"
                    data-testid="search-result-internal-id"
                  >{{ t("nav.internalBadge") }}: {{ result.internal_id }}</span>
                  <span class="shrink-0 text-xs opacity-60" data-testid="search-result-meta">
                    <template v-if="result.assembly || result.assembly_id != null">
                      {{ t("search.assemblyLabel") }}
                      {{ result.assembly ?? result.assembly_id }}
                    </template>
                    <template v-if="result.release_id != null">
                      · {{ t("search.releaseLabel") }} {{ result.release_id }}
                    </template>
                    <template v-if="result.source">
                      · {{ t("search.sourceLabel") }} {{ result.source }}
                    </template>
                  </span>
                  <AppIcon name="arrow-right" class="size-4 shrink-0 text-muted-foreground" />
                </a>
                <div
                  v-else
                  data-testid="search-result-disabled"
                  class="flex items-center gap-3 rounded-xl border bg-card p-4 opacity-60"
                >
                  <span
                    class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"
                  >
                    <AppIcon :name="resultIcon(result.type)" class="size-4" />
                  </span>
                  <Tag class="font-mono uppercase">{{ result.type }}</Tag>
                  <span class="min-w-0 flex-1 truncate font-medium">{{ result.name ?? result.public_id ?? result.id }}</span>
                  <!-- OPT-06: optional, defensive. An older payload omits both. -->
                  <Tag
                    v-if="result.match_type"
                    data-testid="search-result-match-type"
                    class="shrink-0 font-mono text-xs"
                  >{{ result.match_type }}</Tag>
                  <span
                    v-if="result.cross_version?.length"
                    data-testid="search-cross-version"
                    class="shrink-0 text-xs opacity-60"
                  >{{ result.cross_version.map((link) => link.gene_accession).join(", ") }}</span>
                  <span
                    class="shrink-0 font-mono text-xs opacity-70"
                    data-testid="search-result-public-id"
                  >{{ result.public_id ?? result.id }}</span>
                  <span
                    v-if="site.isInternal && result.internal_id"
                    class="shrink-0 font-mono text-xs opacity-60"
                    data-testid="search-result-internal-id"
                  >{{ t("nav.internalBadge") }}: {{ result.internal_id }}</span>
                  <span class="shrink-0 text-xs opacity-60" data-testid="search-result-meta">
                    <template v-if="result.assembly || result.assembly_id != null">
                      {{ t("search.assemblyLabel") }}
                      {{ result.assembly ?? result.assembly_id }}
                    </template>
                    <template v-if="result.release_id != null">
                      · {{ t("search.releaseLabel") }} {{ result.release_id }}
                    </template>
                    <template v-if="result.source">
                      · {{ t("search.sourceLabel") }} {{ result.source }}
                    </template>
                  </span>
                  <AppIcon name="arrow-right" class="size-4 shrink-0 text-muted-foreground" />
                </div>
              </li>
            </ul>
          </div>
        </div>
        <div v-if="results.length > 0" class="mt-6 flex flex-wrap items-center gap-3">
          <Button :disabled="!canPrevious" data-testid="search-previous" @click="previousPage">
            <AppIcon name="chevron-left" class="mr-1 inline size-4" />
            {{ t("common.previous") }}
          </Button>
          <Button :disabled="!canNext" data-testid="search-next" @click="nextPage">
            {{ t("common.next") }}
            <AppIcon name="chevron-right" class="ml-1 inline size-4" />
          </Button>
        </div>
      </section>
    </div>
  </PortalLayout>
</template>
