<script setup lang="ts">
import { useMutation } from "@tanstack/vue-query";
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { adminImportsApi, type ImportTask } from "@soymutdb/api-client";
import { Button, ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Start an import (P1-06).
 *
 * The old `/imports/new` deep link used to land on a "not restored" page. This
 * restores the create step for a file already placed in object storage; the
 * multipart browser upload needs object storage and is a separate capability.
 * An idempotency key is generated per submission so a double click cannot
 * enqueue the same import twice.
 */
const router = useRouter();
const errorMessage = ref("");
const IMPORT_TYPES = [
  "vcf",
  "gff3",
  "fasta",
  "blast_db",
  "seed_data",
  "expression_csv",
  "homolog_csv",
  "module_tsv",
] as const;

const form = reactive({
  filename: "",
  type: "vcf" as (typeof IMPORT_TYPES)[number],
  objectKey: "",
  assembly: "",
  releaseId: "",
});

const createMutation = useMutation({
  mutationFn: () =>
    adminImportsApi.create({
      filename: form.filename.trim(),
      type: form.type,
      object_key: form.objectKey.trim() || undefined,
      file_path: form.objectKey.trim() || undefined,
      assembly: form.assembly.trim() || undefined,
      release_id: form.releaseId ? Number(form.releaseId) : undefined,
      idempotency_key:
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    }),
  onSuccess: (task: ImportTask) => {
    void router.push(`/imports/${task.id}`);
  },
  onError: () => {
    errorMessage.value = t("admin.importCreate.error");
  },
});
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="max-w-xl">
      <RouterLink to="/imports" class="text-sm opacity-70" data-testid="import-create-back">
        ← {{ t("admin.importDetail.back") }}
      </RouterLink>
      <h1 class="mt-2 text-xl font-semibold">{{ t("admin.importCreate.title") }}</h1>
      <p class="mt-2 text-sm opacity-70">{{ t("admin.importCreate.hint") }}</p>

      <form class="mt-4 grid gap-3" @submit.prevent="createMutation.mutate()">
        <label class="text-sm opacity-70">
          {{ t("admin.importCreate.filename") }}
          <input
            v-model="form.filename"
            required
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono text-xs"
            data-testid="import-create-filename"
          />
        </label>
        <label class="text-sm opacity-70">
          {{ t("admin.importCreate.type") }}
          <select
            v-model="form.type"
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
            data-testid="import-create-type"
          >
            <option v-for="value in IMPORT_TYPES" :key="value" :value="value">{{ value }}</option>
          </select>
        </label>
        <label class="text-sm opacity-70">
          {{ t("admin.importCreate.objectKey") }}
          <input
            v-model="form.objectKey"
            class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono text-xs"
            data-testid="import-create-object-key"
          />
        </label>
        <label class="text-sm opacity-70">
          {{ t("admin.importCreate.assembly") }}
          <input v-model="form.assembly" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" data-testid="import-create-assembly" />
        </label>
        <label class="text-sm opacity-70">
          {{ t("admin.importCreate.releaseId") }}
          <input v-model="form.releaseId" type="number" min="1" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" data-testid="import-create-release" />
        </label>
        <p v-if="errorMessage" role="alert" class="text-sm text-red-700" data-testid="import-create-error">
          {{ errorMessage }}
        </p>
        <div>
          <Button html-type="submit" :disabled="createMutation.isPending.value" data-testid="import-create-submit">
            {{ t("admin.importCreate.submit") }}
          </Button>
        </div>
      </form>
    </div>
  </ConfigProvider>
</template>
