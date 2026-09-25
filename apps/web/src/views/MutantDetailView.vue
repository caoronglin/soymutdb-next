<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";
import { useRoute } from "vue-router";

import type { PhenotypeResponse } from "@soymutdb/api-client";
import { ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import {
  mutantLinePhenotypesQueryOptions,
  mutantLineQueryOptions,
} from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

// Public mutant detail (Phase F, DB-CORE-2). The record is addressed + rendered
// by its public_id ONLY; the private internal persistence key is never sent to
// or rendered on the external site (the API response omits it, and the view
// never accepts or displays an internal id). is_public/unreleased handling is
// server-side.
const route = useRoute();
const site = useSiteContextStore();
const publicId = computed(() => String(route.params.publicId));

const query = useQuery(
  computed(() =>
    mutantLineQueryOptions({
      publicId: publicId.value,
      // The api-client sends the pinned release as X-SoyMutDB-Release, so the
      // cache key must carry the same release (never a hard-coded null).
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
    }),
  ),
);

const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const line = computed(() => toValue(query.data));

// Observations are read under the same release/site context as the line; the
// query waits for the detail so an unknown public id does not fire a second
// request whose only possible answer is 404 (mirrors the React route).
const phenotypesQuery = useQuery(
  computed(() =>
    mutantLinePhenotypesQueryOptions({
      publicId: publicId.value,
      releaseId: site.releaseId,
      siteVariant: site.siteVariant,
      enabled: Boolean(line.value),
    }),
  ),
);
const phenotypesLoading = computed(() => toValue(phenotypesQuery.isLoading));
const phenotypesError = computed(() => toValue(phenotypesQuery.isError));
const phenotypes = computed<PhenotypeResponse[]>(() => toValue(phenotypesQuery.data) ?? []);

function displayValue(value: string | null): string {
  return value ?? "—";
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="mx-auto max-w-3xl p-8">
      <p class="text-sm opacity-70"><RouterLink to="/mutants" class="underline">Mutant lines</RouterLink></p>

      <div v-if="isLoading" data-testid="mutant-loading" class="mt-6 h-24 animate-pulse rounded bg-black/5" />
      <div v-else-if="isError" data-testid="mutant-error" class="mt-6 rounded border border-red-300 p-5">
        <p class="font-medium">This mutant line is unavailable.</p>
      </div>

      <article v-else-if="line" data-testid="mutant-detail" class="mt-4">
        <div class="flex items-center gap-2">
          <Tag class="font-mono uppercase">mutant</Tag>
          <h1 class="text-2xl font-semibold" data-testid="mutant-name">{{ line.name }}</h1>
          <span class="ml-auto font-mono text-sm opacity-70" data-testid="mutant-public-id">
            {{ line.public_id }}
          </span>
        </div>

        <dl class="mt-4 grid grid-cols-2 gap-2 text-sm">
          <dt class="opacity-70">Mutagen</dt>
          <dd data-testid="mutant-mutagen">{{ line.mutagen ?? "—" }}</dd>
          <dt class="opacity-70">Cultivar</dt>
          <dd>{{ line.cultivar ?? "—" }}</dd>
          <dt class="opacity-70">Generation</dt>
          <dd>{{ line.generation ?? "—" }}</dd>
          <dt class="opacity-70">Species</dt>
          <dd>{{ line.species }}</dd>
          <dt class="opacity-70">Linked variants</dt>
          <dd>{{ line.variant_count }}</dd>
        </dl>

        <p v-if="line.phenotype_summary" class="mt-4 text-sm">{{ line.phenotype_summary }}</p>
        <p v-if="line.description" class="mt-2 text-sm opacity-80">{{ line.description }}</p>

        <section
          class="mt-8"
          aria-labelledby="mutant-phenotypes"
          data-testid="mutant-phenotypes"
        >
          <h2 id="mutant-phenotypes" class="text-lg font-medium">Phenotype observations</h2>
          <p class="mt-1 text-xs opacity-60">
            Observations recorded for this line; they do not by themselves establish causality.
          </p>
          <p
            v-if="phenotypesLoading"
            data-testid="phenotypes-loading"
            class="mt-3 text-sm opacity-70"
          >
            Loading phenotypes…
          </p>
          <p
            v-else-if="phenotypesError"
            data-testid="phenotypes-error"
            class="mt-3 text-sm opacity-70"
          >
            Could not load phenotypes.
          </p>
          <p
            v-else-if="phenotypes.length === 0"
            data-testid="phenotypes-empty"
            class="mt-3 text-sm opacity-70"
          >
            No phenotypes recorded.
          </p>
          <table v-else class="mt-3 w-full text-sm" data-testid="phenotypes-table">
            <thead class="text-left opacity-60">
              <tr>
                <th>Category</th>
                <th>Name</th>
                <th>Value</th>
                <th>Unit</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="phenotype in phenotypes" :key="phenotype.id" data-testid="phenotype-row">
                <td>{{ phenotype.trait_category }}</td>
                <td>{{ phenotype.trait_name }}</td>
                <td>{{ displayValue(phenotype.trait_value) }}</td>
                <td>{{ displayValue(phenotype.unit) }}</td>
                <td>{{ displayValue(phenotype.description) }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <!-- DB-CORE-2: no internal identifier is ever rendered on the public site. -->
      </article>

      <div v-else data-testid="mutant-empty" class="mt-6 text-sm opacity-70">Mutant line not found.</div>
    </div>
  </ConfigProvider>
</template>
