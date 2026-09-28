<script setup lang="ts">
import { useMutation, useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import {
  getBlastDatabases,
  getBlastHits,
  getBlastJobs,
  submitBlastJob,
  type BlastDatabase,
  type BlastHit,
  type BlastJob,
} from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";
import { compactGeneId } from "@soymutdb/shared/genomics";

import PortalLayout from "../components/PortalLayout.vue";
import { isJbrowseEnabled, resolveJbrowseBaseUrl } from "../lib/deployment";
import { t } from "../lib/i18n";
import { useSiteContent } from "../lib/site-content";

/**
 * BLAST — sequence homology search against a named database.
 *
 * The database list is server-provided rather than hard-coded, so a database
 * that the deployment has not activated cannot be selected (and therefore
 * cannot silently return an empty or ambiguous result).
 */
const PROGRAMMES = ["blastn", "blastp", "blastx", "tblastn", "tblastx"] as const;

// Operator-editable copy (admin `content.*` rows). `get` returns the stored
// override or the localized `t(...)` fallback; an unedited deployment keeps
// today's exact strings.
const { get } = useSiteContent();

const sequence = ref("");
const programme = ref<string>("blastn");
const database = ref("");
const jobName = ref("");
const eValue = ref("10");
const maxHits = ref("50");
const selectedJobId = ref<string | null>(null);
const submittedJobId = ref<string | null>(null);

const databasesQuery = useQuery({
  queryKey: ["blast", "databases"],
  queryFn: getBlastDatabases,
  staleTime: 5 * 60_000,
});
const databases = computed<BlastDatabase[]>(() => toValue(databasesQuery.data) ?? []);
const activeDatabases = computed(() => databases.value.filter((item) => item.is_active));
const databasesLoading = computed(() => toValue(databasesQuery.isLoading));

const jobsQuery = useQuery({
  queryKey: ["blast", "jobs", 1, 5],
  queryFn: () => getBlastJobs({ page: 1, page_size: 5 }),
  staleTime: 30_000,
});
const jobs = computed<BlastJob[]>(() => toValue(jobsQuery.data)?.items ?? []);

const submitMutation = useMutation({
  mutationFn: submitBlastJob,
  onSuccess: (job: BlastJob) => {
    selectedJobId.value = job.id;
    submittedJobId.value = job.id;
    void jobsQuery.refetch();
  },
});

const hitsQuery = useQuery(
  computed(() => ({
    queryKey: ["blast", "hits", selectedJobId.value ?? null],
    queryFn: () => getBlastHits(selectedJobId.value!, { limit: 100, offset: 0 }),
    enabled: Boolean(selectedJobId.value),
    staleTime: 30_000,
  })),
);

const hits = computed<BlastHit[]>(() => toValue(hitsQuery.data)?.items ?? []);
const isSubmitting = computed(() => toValue(submitMutation.isPending));

const selectedJob = computed<BlastJob | undefined>(() => {
  const id = selectedJobId.value;
  if (!id) return undefined;
  return (
    jobs.value.find((job) => job.id === id) ??
    (toValue(submitMutation.data)?.id === id ? toValue(submitMutation.data) : undefined)
  );
});

/**
 * React parity (blast.tsx `assemblyForJob`): the job stores the database *name*,
 * so map it back to the assembly that database belongs to — name match first,
 * then id match — before building a JBrowse deep link.
 */
function assemblyForJob(job: BlastJob | undefined): string | undefined {
  if (!job) return undefined;
  const byName = databases.value.find((item) => item.name === job.database);
  if (byName?.assembly_name) return byName.assembly_name;
  return databases.value.find((item) => String(item.id) === String(job.database))?.assembly_name ?? undefined;
}

/** Hit → gene-ID search (`/search/genes?q=…&run=true`, React's gene column). */
function hitGeneHref(hit: BlastHit): string | undefined {
  const geneId = hit.subject_id?.trim();
  if (!geneId) return undefined;
  return `/search/genes?${new URLSearchParams({ q: geneId, run: "true" }).toString()}`;
}

/** Hit → JBrowse 2 locus (`subject_id:start..end`, React's gbrowse column). */
function hitJbrowseHref(hit: BlastHit): string | undefined {
  // A core-only deployment runs no genome browser: never link into a dead frame.
  if (!isJbrowseEnabled()) return undefined;
  if (!hit.subject_id || hit.subject_start == null || hit.subject_end == null) return undefined;
  const params = new URLSearchParams({ loc: `${hit.subject_id}:${hit.subject_start}..${hit.subject_end}` });
  const assembly = assemblyForJob(selectedJob.value);
  if (assembly) params.set("assembly", assembly);
  return `${resolveJbrowseBaseUrl(import.meta.env.VITE_JBROWSE_BASE_URL)}?${params.toString()}`;
}

function submit() {
  const trimmed = sequence.value.trim();
  if (!trimmed || !database.value) return;
  submitMutation.mutate({
    program: programme.value,
    database: database.value,
    sequence: trimmed,
    name: jobName.value.trim() || undefined,
    e_value: Number(eValue.value) || undefined,
    max_hits: Number(maxHits.value) || undefined,
  });
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-7xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("blast.title") }}</h1>
      <p class="mt-1 max-w-2xl text-sm opacity-70">{{ t("blast.subtitle") }}</p>

      <form class="mt-6 grid gap-4 lg:grid-cols-[2fr_1fr]" @submit.prevent="submit">
        <label class="text-sm opacity-70">
          {{ get("blast.input", t("blast.inputSequence")) }}
          <textarea
            v-model="sequence"
            rows="8"
            class="mt-1 w-full rounded-md border bg-background p-3 font-mono text-sm"
            :placeholder="get('blast.sequencePlaceholder', t('blast.sequencePlaceholder'))"
            data-testid="blast-sequence"
          />
        </label>
        <div class="grid content-start gap-3">
          <label class="text-sm opacity-70">
            {{ get("blast.searchType", t("blast.searchType")) }}
            <select v-model="programme" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" data-testid="blast-program">
              <option v-for="item in PROGRAMMES" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="text-sm opacity-70">
            {{ get("blast.database", t("blast.database")) }}
            <select
              v-model="database"
              class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
              :disabled="activeDatabases.length === 0"
              data-testid="blast-database"
            >
              <option value="" disabled>
                {{ databasesLoading ? get("ui.loading", t("common.loading")) : get("blast.databasePlaceholder", t("blast.databasePlaceholder")) }}
              </option>
              <option v-for="item in activeDatabases" :key="String(item.id)" :value="String(item.id)">
                {{ item.name }} ({{ item.db_type }})
              </option>
            </select>
          </label>
          <label class="text-sm opacity-70">
            {{ t("blast.jobName") }}
            <input v-model="jobName" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" data-testid="blast-name" />
          </label>
          <label class="text-sm opacity-70">
            {{ t("blast.eValue") }}
            <input v-model="eValue" type="number" step="any" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" />
          </label>
          <label class="text-sm opacity-70">
            {{ t("blast.maxHits") }}
            <input v-model="maxHits" type="number" min="1" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" />
          </label>
          <Button html-type="submit" :disabled="isSubmitting || !sequence.trim() || !database" data-testid="blast-submit">
            {{ isSubmitting ? t("blast.running") : get("blast.submit", t("blast.submit")) }}
          </Button>
        </div>
      </form>

      <p v-if="toValue(submitMutation.isError)" class="mt-4 text-sm text-red-700" data-testid="blast-error" role="alert">
        {{ t("common.error") }}
      </p>
      <p v-if="submittedJobId" class="mt-4 text-sm opacity-70" data-testid="blast-submitted">
        {{ t("blast.viewResults") }}: <span class="font-mono">{{ submittedJobId }}</span>
      </p>

      <section class="mt-8" :aria-label="t('blast.recentJobs')">
        <h2 class="text-lg font-medium">{{ t("blast.jobHistory") }}</h2>
        <ul class="mt-2 grid gap-1" data-testid="blast-jobs">
          <li v-for="job in jobs" :key="job.id">
            <button type="button" class="underline" :data-testid="`blast-job-${job.id}`" @click="selectedJobId = job.id">
              {{ job.name || job.id }} · {{ job.status }} · {{ job.hit_count }}
            </button>
          </li>
        </ul>
      </section>

      <section class="mt-8" :aria-label="t('blast.hitsAria')">
        <h2 class="text-lg font-medium">{{ t("blast.hits") }}</h2>
        <p v-if="!selectedJobId" data-testid="blast-hits-empty" class="mt-2 text-sm opacity-70">
          {{ get("ui.noResults", t("blast.noJobs")) }}
        </p>
        <p v-else-if="toValue(hitsQuery.isLoading)" class="mt-2 text-sm opacity-70">{{ t("common.loading") }}</p>
        <p v-else-if="hits.length === 0" data-testid="blast-hits-none" class="mt-2 text-sm opacity-70">
          {{ get("ui.noResults", t("blast.noHits")) }}
        </p>
        <table v-else class="mt-2 w-full text-sm" data-testid="blast-hits-table">
          <thead class="text-left opacity-60">
            <tr>
              <th class="py-2">{{ get("blast.hitSequenceId", t("blast.hitSequenceId")) }}</th>
              <th class="py-2">{{ get("blast.hitCoverage", t("blast.hitCoverage")) }}</th>
              <th class="py-2">{{ t("blast.alignmentLength") }}</th>
              <th class="py-2">{{ get("blast.hitEValue", t("blast.hitEValue")) }}</th>
              <th class="py-2">{{ t("blast.hitScore") }}</th>
              <!-- React parity: the hit table also exposes the two jumps the
                   Vue port was missing — into the gene-ID search and into the
                   JBrowse locus for the hit's coordinates. -->
              <th class="py-2">{{ get("blast.hitGeneId", t("blast.hitGeneId")) }}</th>
              <th class="py-2">{{ t("blast.actions.gbrowse") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(hit, index) in hits" :key="`${hit.subject_id}-${index}`" data-testid="blast-hit" class="border-t">
              <td class="py-2 font-mono text-xs">{{ hit.subject_id }}</td>
              <td class="py-2 font-mono text-xs">{{ hit.percent_identity }}%</td>
              <td class="py-2 font-mono text-xs">{{ hit.alignment_length }}</td>
              <td class="py-2 font-mono text-xs">{{ hit.evalue }}</td>
              <td class="py-2 font-mono text-xs">{{ hit.bit_score }}</td>
              <td class="py-2">
                <RouterLink
                  v-if="hitGeneHref(hit)"
                  :to="hitGeneHref(hit)!"
                  class="text-primary underline"
                  :title="hit.subject_id"
                  :data-testid="`blast-hit-gene-${index}`"
                >
                  {{ compactGeneId(hit.subject_id, 18) }}
                </RouterLink>
                <span v-else class="opacity-60">{{ t("blast.actions.geneSearch") }}</span>
              </td>
              <td class="py-2">
                <a
                  v-if="hitJbrowseHref(hit)"
                  :href="hitJbrowseHref(hit)!"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-primary underline"
                  :data-testid="`blast-hit-gbrowse-${index}`"
                >
                  {{ t("blast.actions.gbrowse") }}
                </a>
                <span v-else class="opacity-60" :data-testid="`blast-hit-gbrowse-unavailable-${index}`">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  </PortalLayout>
</template>
