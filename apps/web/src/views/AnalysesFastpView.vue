<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";


import PortalLayout from "../components/PortalLayout.vue";
import ResearcherGate from "../components/ResearcherGate.vue";
import { t } from "../lib/i18n";
import { useAnalysisJobForm } from "../lib/use-analysis-job-form";

/**
 * fastp submission page — FASTQ QC pipeline.
 *
 * Single-end (one file) or paired-end (R1 then R2) FASTQ inputs, each ≤ 500 MB.
 * Files go straight to object storage through a presigned POST; the job is
 * submitted only after every upload succeeded. Parameters are validated against
 * the server whitelist client-side so an obviously invalid job is rejected
 * before any bytes move.
 */
const FASTQ_EXTENSIONS = [".fq", ".fq.gz", ".fastq", ".fastq.gz"] as const;

const router = useRouter();
const { files, isPending, progress, errorMessage, fieldErrors, setFiles, submit } =
  useAnalysisJobForm("fastp");

const params = ref<Record<string, string>>({ trim_front1: "0", trim_tail1: "0", quality_phred: "15", thread: "4" });

const paramKeys = Object.keys(params.value);

const RANGES: Record<string, [number, number]> = {
  trim_front1: [0, 1000],
  trim_tail1: [0, 1000],
  quality_phred: [0, 40],
  thread: [1, 64],
};

function validate(): boolean {
  const errors: Record<string, string> = {};
  for (const [key, [lo, hi]] of Object.entries(RANGES)) {
    const value = Number(params.value[key]);
    if (!Number.isFinite(value) || value < lo || value > hi) {
      errors[key] = `${key} must be between ${lo} and ${hi}`;
    }
  }
  fieldErrors.value = errors;
  return Object.keys(errors).length === 0;
}

async function onSubmit() {
  if (!validate()) return;
  await submit(files.value, { ...params.value }, router);
}

function onFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  const selected = Array.from(input.files ?? []);
  if (!FASTQ_EXTENSIONS.some((extension) => selected.every((file) => file.name.endsWith(extension)))) {
    errorMessage.value = "Select FASTQ files (.fq, .fq.gz, .fastq, .fastq.gz).";
    return;
  }
  errorMessage.value = "";
  setFiles(selected);
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-3xl px-4 py-8">
      <ResearcherGate>
        <h1 class="text-2xl font-semibold">{{ t("analyses.fastp.title") }}</h1>
        <p class="mt-1 text-sm opacity-70">{{ t("analyses.fastp.subtitle") }}</p>

        <form class="mt-6 grid gap-4" @submit.prevent="onSubmit">
          <label class="text-sm opacity-70">
            {{ t("analyses.fastp.files") }}
            <input
              type="file"
              multiple
              accept=".fq,.fq.gz,.fastq,.fastq.gz"
              class="mt-1 block w-full text-sm"
              data-testid="fastp-files"
              @change="onFiles"
            />
          </label>

          <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <label v-for="key in paramKeys" :key="key" class="text-sm opacity-70">
              {{ key }}
              <input
                v-model="params[key]"
                class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono"
                :data-testid="'fastp-' + key"
              />
              <span v-if="fieldErrors[key as string]" class="text-xs text-red-700">
                {{ fieldErrors[key] }}
              </span>
            </label>
          </div>

          <p v-if="errorMessage" class="text-sm text-red-700" role="alert" data-testid="fastp-error">
            {{ errorMessage }}
          </p>
          <p v-if="progress > 0" class="text-sm opacity-70" data-testid="fastp-progress">
            {{ progress }}%
          </p>

          <button
            type="submit"
            class="w-fit rounded-md border px-4 py-2 text-sm font-medium disabled:opacity-50"
            :disabled="isPending || files.length === 0"
            data-testid="fastp-submit"
          >
            {{ isPending ? t("common.loading") : t("analyses.submit") }}
          </button>
        </form>

        <p class="mt-4 text-xs opacity-60">{{ t("analyses.maxFileSize") }}</p>
      </ResearcherGate>
    </div>
  </PortalLayout>
</template>
