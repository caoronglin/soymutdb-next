<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { getAnalysis, getAnalysisDownload } from "@soymutdb/api-client";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Analysis job detail — status, parameters, and the result download.
 *
 * The download URL is requested from the API (short-lived, scoped to the job
 * owner) instead of being derived client-side, so an expired or foreign job
 * cannot be fetched by guessing a path.
 */
const props = defineProps<{ jobId: string }>();

const site = useSiteContextStore();

const query = useQuery({
  queryKey: ["analysis-job", props.jobId, site.releaseId, site.siteVariant],
  queryFn: () => getAnalysis(props.jobId),
  staleTime: 10_000,
});

const job = computed(() => toValue(query.data));
const isPending = computed(() => toValue(query.isPending));
const isError = computed(() => toValue(query.isError));

const downloadUrl = ref<string | null>(null);
const downloadError = ref("");
const isPreparing = ref(false);

const objectKey = computed(() => {
  const result = job.value?.result;
  if (result && typeof result === "object" && "output_objects" in result) {
    const objects = (result as { output_objects?: unknown }).output_objects;
    if (Array.isArray(objects) && typeof objects[0] === "string") return objects[0];
  }
  return null;
});

async function prepareDownload() {
  if (!objectKey.value) {
    downloadError.value = t("common.errorDescription");
    return;
  }
  isPreparing.value = true;
  downloadError.value = "";
  try {
    const response = await getAnalysisDownload(props.jobId, objectKey.value);
    downloadUrl.value = response.download_url;
  } catch {
    downloadError.value = t("common.error");
  } finally {
    isPreparing.value = false;
  }
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-3xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("analyses.job.title") }}</h1>
      <p class="mt-1 font-mono text-sm opacity-70" data-testid="analysis-job-id">{{ jobId }}</p>

      <p v-if="isPending" data-testid="analysis-job-loading" class="mt-6 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <p v-else-if="isError" data-testid="analysis-job-error" class="mt-6 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <template v-else-if="job">
        <dl class="mt-6 grid gap-3 sm:grid-cols-2" data-testid="analysis-job-detail">
          <div>
            <dt class="text-sm opacity-70">{{ t("common.status") }}</dt>
            <dd class="font-mono" data-testid="analysis-job-status">{{ job.status }}</dd>
          </div>
          <div>
            <dt class="text-sm opacity-70">{{ t("common.date") }}</dt>
            <dd>{{ job.created_at ?? "—" }}</dd>
          </div>
          <div v-if="job.error_message" class="sm:col-span-2">
            <dt class="text-sm opacity-70">{{ t("common.error") }}</dt>
            <dd class="text-sm text-red-700">{{ job.error_message }}</dd>
          </div>
        </dl>

        <div class="mt-6">
          <button
            type="button"
            class="rounded-md border px-4 py-2 text-sm font-medium"
            :disabled="isPreparing || job.status !== 'succeeded'"
            data-testid="analysis-job-download"
            @click="prepareDownload"
          >
            {{ isPreparing ? t("common.loading") : t("common.download") }}
          </button>
          <a
            v-if="downloadUrl"
            :href="downloadUrl"
            class="ms-3 text-sm underline"
            data-testid="analysis-job-download-link"
          >
            {{ t("common.download") }}
          </a>
          <p v-if="downloadError" class="mt-2 text-sm text-red-700">{{ downloadError }}</p>
        </div>
      </template>
    </div>
  </PortalLayout>
</template>
