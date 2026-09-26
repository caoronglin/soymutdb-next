<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue } from "vue";
import { useRoute } from "vue-router";

import { adminImportsApi, type ImportLiveStatus } from "@soymutdb/api-client";
import { formatDate } from "@soymutdb/shared/format";
import { Button, ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Import task detail + live status (P1-06).
 *
 * This is the surface the old `/imports/:taskId` deep link used to reach. The
 * status block polls the server's live state (including the Celery state) and
 * never derives success on the client. Retry is offered only for a failed task
 * and cancel only while the task is still active, mirroring the API contract.
 */
const route = useRoute();
const queryClient = useQueryClient();
const taskId = computed(() => Number(route.params.taskId));
const enabled = computed(() => Number.isInteger(taskId.value) && taskId.value > 0);

const detailQuery = useQuery({
  queryKey: computed(() => ["admin", "imports", "detail", taskId.value]),
  queryFn: () => adminImportsApi.get(taskId.value),
  enabled,
  retry: false,
});

const statusQuery = useQuery({
  queryKey: computed(() => ["admin", "imports", "status", taskId.value]),
  queryFn: () => adminImportsApi.status(taskId.value),
  enabled,
  retry: false,
  refetchInterval: 5000,
});

const task = computed(() => toValue(detailQuery.data));
const live = computed<ImportLiveStatus | undefined>(() => toValue(statusQuery.data));

const ACTIVE_STATUSES = ["uploading", "validating", "ingesting", "queued", "running"];
const canRetry = computed(() => task.value?.status === "failed");
const canCancel = computed(() => ACTIVE_STATUSES.includes(task.value?.status ?? ""));

const invalidate = () => {
  void queryClient.invalidateQueries({ queryKey: ["admin", "imports"] });
};
const retryMutation = useMutation({
  mutationFn: () => adminImportsApi.retry(taskId.value),
  onSuccess: invalidate,
});
const cancelMutation = useMutation({
  mutationFn: () => adminImportsApi.cancel(taskId.value),
  onSuccess: invalidate,
});
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div>
      <RouterLink to="/imports" class="text-sm opacity-70" data-testid="import-detail-back">
        ← {{ t("admin.importDetail.back") }}
      </RouterLink>
      <h1 class="mt-2 text-xl font-semibold">
        {{ t("admin.importDetail.title") }}
        <span v-if="task" class="ms-2 font-mono text-sm opacity-70">#{{ task.id }}</span>
      </h1>

      <p
        v-if="detailQuery.isError.value"
        role="alert"
        data-testid="import-detail-error"
        class="mt-4 text-sm text-red-700"
      >
        {{ t("admin.importDetail.loadError") }}
      </p>
      <p v-else-if="detailQuery.isPending.value" class="mt-4 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <dl v-else-if="task" class="mt-4 grid gap-2 text-sm sm:grid-cols-2">
        <div><dt class="opacity-60">{{ t("admin.importDetail.filename") }}</dt><dd class="font-mono">{{ task.filename }}</dd></div>
        <div><dt class="opacity-60">{{ t("admin.importDetail.type") }}</dt><dd>{{ task.type }}</dd></div>
        <div><dt class="opacity-60">{{ t("admin.importDetail.status") }}</dt><dd><Tag data-testid="import-detail-status">{{ task.status }}</Tag></dd></div>
        <div><dt class="opacity-60">{{ t("admin.importDetail.celeryStatus") }}</dt><dd>{{ live?.celery_status ?? "—" }}</dd></div>
        <div><dt class="opacity-60">{{ t("admin.importDetail.processed") }}</dt><dd>{{ live?.processed_records ?? task.processed_records ?? 0 }} / {{ live?.total_records ?? task.total_records ?? 0 }}</dd></div>
        <div><dt class="opacity-60">{{ t("admin.importDetail.progress") }}</dt><dd>{{ live?.progress ?? task.progress ?? 0 }}%</dd></div>
        <div><dt class="opacity-60">{{ t("admin.importDetail.submittedBy") }}</dt><dd>{{ task.submitted_by ?? "—" }}</dd></div>
        <div><dt class="opacity-60">{{ t("admin.importDetail.submittedAt") }}</dt><dd>{{ formatDate(task.submitted_at) }}</dd></div>
        <div><dt class="opacity-60">{{ t("admin.importDetail.completedAt") }}</dt><dd>{{ task.completed_at ? formatDate(task.completed_at) : "—" }}</dd></div>
        <div class="sm:col-span-2"><dt class="opacity-60">{{ t("admin.importDetail.filePath") }}</dt><dd class="break-all font-mono text-xs">{{ task.file_path ?? "—" }}</dd></div>
        <div v-if="live?.error_message || task.error_message" class="sm:col-span-2">
          <dt class="opacity-60">{{ t("admin.importDetail.errorMessage") }}</dt>
          <dd class="text-red-700" data-testid="import-detail-error-message">{{ live?.error_message || task.error_message }}</dd>
        </div>
      </dl>

      <div class="mt-6 flex gap-2">
        <Button v-if="canRetry" data-testid="import-detail-retry" :disabled="retryMutation.isPending.value" @click="retryMutation.mutate()">
          {{ t("admin.importDetail.retry") }}
        </Button>
        <Button v-if="canCancel" data-testid="import-detail-cancel" :disabled="cancelMutation.isPending.value" @click="cancelMutation.mutate()">
          {{ t("admin.importDetail.cancel") }}
        </Button>
      </div>
    </div>
  </ConfigProvider>
</template>
