<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";


import PortalLayout from "../components/PortalLayout.vue";
import ResearcherGate from "../components/ResearcherGate.vue";
import { t } from "../lib/i18n";
import { useAnalysisJobForm } from "../lib/use-analysis-job-form";

/**
 * scanpy submission page — single-cell clustering pipeline.
 *
 * One .h5ad (AnnData) file ≤ 500 MB, presigned to object storage, then a scanpy
 * job (filtering → HVG selection → PCA → Leiden clustering).
 */
const H5AD_EXTENSIONS = [".h5ad"] as const;

const router = useRouter();
const { files, isPending, progress, errorMessage, fieldErrors, setFiles, submit } =
  useAnalysisJobForm("scanpy");

const params = ref<Record<string, string>>({ min_genes: "200", min_cells: "3", n_top_genes: "2000", resolution: "1.0" });
const useHvg = ref(true);

const paramKeys = Object.keys(params.value);

const RANGES: Record<string, [number, number]> = {
  min_genes: [1, 100_000],
  min_cells: [1, 1_000_000],
  n_top_genes: [1, 100_000],
  resolution: [0.1, 10.0],
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
  await submit(files.value, { ...params.value, use_hvg: useHvg.value }, router);
}

function onFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  const selected = Array.from(input.files ?? []);
  if (!H5AD_EXTENSIONS.every((extension) => selected.length > 0 && selected.every((file) => file.name.endsWith(extension)))) {
    errorMessage.value = "Select one AnnData .h5ad file.";
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
        <h1 class="text-2xl font-semibold">{{ t("analyses.scanpy.title") }}</h1>
        <p class="mt-1 text-sm opacity-70">{{ t("analyses.scanpy.subtitle") }}</p>

        <form class="mt-6 grid gap-4" @submit.prevent="onSubmit">
          <label class="text-sm opacity-70">
            {{ t("analyses.scanpy.files") }}
            <input
              type="file"
              accept=".h5ad"
              class="mt-1 block w-full text-sm"
              data-testid="scanpy-files"
              @change="onFiles"
            />
          </label>

          <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <label v-for="key in paramKeys" :key="key" class="text-sm opacity-70">
              {{ key }}
              <input
                v-model="params[key]"
                class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono"
                :data-testid="'scanpy-' + key"
              />
              <span v-if="fieldErrors[key as string]" class="text-xs text-red-700">
                {{ fieldErrors[key] }}
              </span>
            </label>
          </div>

          <label class="flex items-center gap-2 text-sm">
            <input v-model="useHvg" type="checkbox" data-testid="scanpy-use-hvg" />
            {{ t("analyses.scanpy.useHvg") }}
          </label>

          <p v-if="errorMessage" class="text-sm text-red-700" role="alert" data-testid="scanpy-error">
            {{ errorMessage }}
          </p>
          <p v-if="progress > 0" class="text-sm opacity-70" data-testid="scanpy-progress">
            {{ progress }}%
          </p>

          <button
            type="submit"
            class="w-fit rounded-md border px-4 py-2 text-sm font-medium disabled:opacity-50"
            :disabled="isPending || files.length === 0"
            data-testid="scanpy-submit"
          >
            {{ isPending ? t("common.loading") : t("analyses.submit") }}
          </button>
        </form>

        <p class="mt-4 text-xs opacity-60">{{ t("analyses.maxFileSize") }}</p>
      </ResearcherGate>
    </div>
  </PortalLayout>
</template>
