<template>
  <div class="admin-page">
    <AdminPageHeader :title="t('admin.importCreate.title')" :description="t('admin.importCreate.hint')">
      <template #meta>
        <RouterLink to="/imports" class="admin-link mt-2 inline-block" data-testid="import-create-back">
          ← {{ t("admin.importDetail.back") }}
        </RouterLink>
      </template>
    </AdminPageHeader>

    <AdminCard class="max-w-2xl">
      <form class="grid gap-3" @submit.prevent="createMutation.mutate()">
        <label class="admin-field">
          {{ t("admin.importCreate.filename") }}
          <input
            v-model="form.filename"
            required
            class="admin-control admin-control--mono"
            data-testid="import-create-filename"
          />
        </label>
        <label class="admin-field">
          {{ t("admin.importCreate.type") }}
          <select v-model="form.type" class="admin-control" data-testid="import-create-type">
            <option v-for="value in IMPORT_TYPES" :key="value" :value="value">{{ value }}</option>
          </select>
        </label>
        <label class="admin-field">
          {{ t("admin.importCreate.objectKey") }}
          <input
            v-model="form.objectKey"
            class="admin-control admin-control--mono"
            data-testid="import-create-object-key"
          />
        </label>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="admin-field">
            {{ t("admin.importCreate.assembly") }}
            <input
              v-model="form.assembly"
              class="admin-control"
              data-testid="import-create-assembly"
            />
          </label>
          <label class="admin-field">
            {{ t("admin.importCreate.releaseId") }}
            <input
              v-model="form.releaseId"
              type="number"
              min="1"
              class="admin-control"
              data-testid="import-create-release"
            />
          </label>
        </div>

        <p
          v-if="errorMessage"
          role="alert"
          class="admin-state admin-state--error"
          data-testid="import-create-error"
        >
          {{ errorMessage }}
        </p>

        <div class="flex gap-2">
          <Button
            type="primary"
            html-type="submit"
            :disabled="createMutation.isPending.value"
            data-testid="import-create-submit"
          >
            {{ createMutation.isPending.value ? t("common.loading") : t("admin.importCreate.submit") }}
          </Button>
          <RouterLink
            to="/imports"
            class="inline-flex min-h-9 items-center rounded-md border border-border px-3 text-sm"
          >
            {{ t("common.cancel") }}
          </RouterLink>
        </div>
      </form>
    </AdminCard>
  </div>
</template>

<script setup lang="ts">
import { useMutation } from "@tanstack/vue-query";
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { adminImportsApi, type ImportTask } from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
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
