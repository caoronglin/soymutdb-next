<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { fetchSraRun, type SraRunInfo } from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";

/**
 * SRA browser — federated run metadata lookups.
 *
 * The values come from NCBI through the API (this is a federated source, not a
 * SoyMutDB-owned table), so the page shows the accession that produced them and
 * never presents them as released SoyMutDB records.
 */
const accession = ref("");
const submitted = ref("");

const query = useQuery(
  computed(() => ({
    queryKey: ["sra", "run", submitted.value],
    queryFn: () => fetchSraRun(submitted.value),
    enabled: Boolean(submitted.value),
    staleTime: 5 * 60_000,
    retry: false,
  })),
);

const run = computed<SraRunInfo | undefined>(() => toValue(query.data)?.run);
const isPending = computed(() => toValue(query.isPending));
const isError = computed(() => toValue(query.isError));

const FIELDS = [
  "ScientificName",
  "LibraryStrategy",
  "LibraryLayout",
  "Platform",
  "Model",
  "spots",
  "bases",
  "avgLength",
  "size_MB",
  "SRAStudy",
  "BioProject",
  "BioSample",
] as const;

function submit() {
  submitted.value = accession.value.trim();
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-4xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("nav.sra") }}</h1>
      <p class="mt-1 text-sm opacity-70">{{ t("sra.subtitle") }}</p>

      <form class="mt-6 flex flex-wrap items-end gap-3" role="search" @submit.prevent="submit">
        <label class="text-sm opacity-70">
          {{ t("sra.accession") }}
          <input
            v-model="accession"
            class="mt-1 w-56 rounded-md border bg-background px-2 py-1.5 font-mono"
            placeholder="SRR00000000"
            data-testid="sra-accession"
          />
        </label>
        <Button html-type="submit" :disabled="!accession.trim()" data-testid="sra-submit">
          {{ t("common.search") }}
        </Button>
      </form>

      <p v-if="isPending" data-testid="sra-loading" class="mt-6 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <p v-else-if="isError" data-testid="sra-error" class="mt-6 text-sm text-red-700">
        {{ t("sra.notFound") }}
      </p>
      <template v-else-if="run">
        <h2 class="mt-6 font-mono text-lg font-medium" data-testid="sra-run">{{ run.Run }}</h2>
        <dl class="mt-4 grid gap-3 sm:grid-cols-2" data-testid="sra-details">
          <div v-for="field in FIELDS" :key="field">
            <dt class="text-sm opacity-70">{{ field }}</dt>
            <dd class="font-mono text-sm">{{ run[field] ?? "—" }}</dd>
          </div>
        </dl>
        <p class="mt-4 text-sm">
          <a :href="run.sra_url" target="_blank" rel="noopener noreferrer" class="underline">
            {{ t("sra.openInNcbi") }}
          </a>
        </p>
      </template>
      <p v-else class="mt-6 text-sm opacity-70" data-testid="sra-idle">
        {{ t("sra.subtitle") }}
      </p>
    </div>
  </PortalLayout>
</template>
