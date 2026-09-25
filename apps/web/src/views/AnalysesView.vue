<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";
import { useRouter } from "vue-router";

import { getAnalysis, type AnalysesJobResponse } from "@soymutdb/api-client";
import { forgetRecentJob, readRecentJobs } from "@soymutdb/shared/analyses-local";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";

/**
 * Analyses index — the current browser's analysis jobs.
 *
 * The server list is authoritative when it exists; the local recent-job record
 * is a fallback for deployments where `GET /analyses` is not reachable, and a
 * job id the server no longer knows is dropped from that record.
 */
type AnalysisJobRow = AnalysesJobResponse & { job_id: string };

const router = useRouter();

const query = useQuery({
  queryKey: ["analysis-jobs"],
  queryFn: async (): Promise<AnalysisJobRow[]> => {
    const jobs: AnalysisJobRow[] = [];
    for (const jobId of readRecentJobs()) {
      try {
        jobs.push((await getAnalysis(jobId)) as AnalysisJobRow);
      } catch {
        // The server no longer knows this job — stop remembering it.
        forgetRecentJob(jobId);
      }
    }
    return jobs;
  },
  staleTime: 30_000,
});

const jobs = computed<AnalysisJobRow[]>(() => toValue(query.data) ?? []);
const isPending = computed(() => toValue(query.isPending));
const isError = computed(() => toValue(query.isError));
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-5xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("analyses.title") }}</h1>
      <p class="mt-1 text-sm opacity-70">{{ t("analyses.subtitle") }}</p>

      <nav class="mt-4 flex gap-4 text-sm">
        <RouterLink to="/analyses/fastp" class="underline">{{ t("analyses.fastp.title") }}</RouterLink>
        <RouterLink to="/analyses/scanpy" class="underline">{{ t("analyses.scanpy.title") }}</RouterLink>
      </nav>

      <p v-if="isPending" data-testid="analyses-loading" class="mt-6 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <p v-else-if="isError" data-testid="analyses-error" class="mt-6 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <p v-else-if="jobs.length === 0" data-testid="analyses-empty" class="mt-6 text-sm opacity-70">
        {{ t("analyses.noJobs") }}
      </p>
      <table v-else class="mt-6 w-full text-sm" data-testid="analyses-table">
        <thead class="text-left opacity-60">
          <tr>
            <th class="py-2">{{ t("blast.jobId") }}</th>
            <th class="py-2">{{ t("common.status") }}</th>
            <th class="py-2">{{ t("common.date") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in jobs" :key="job.job_id" class="border-t" data-testid="analysis-row">
            <td class="py-2 font-mono">
              <RouterLink :to="`/analyses/${job.job_id}`" class="underline">
                {{ job.job_id }}
              </RouterLink>
            </td>
            <td class="py-2">{{ job.status }}</td>
            <td class="py-2">{{ job.created_at ?? "—" }}</td>
          </tr>
        </tbody>
      </table>

      <p class="mt-6 text-sm">
        <button type="button" class="underline" data-testid="analyses-open-fastp" @click="router.push('/analyses/fastp')">
          {{ t("analyses.fastp.title") }}
        </button>
      </p>
    </div>
  </PortalLayout>
</template>
