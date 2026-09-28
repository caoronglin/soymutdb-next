<template>
  <div class="admin-page">
    <AdminPageHeader
      :title="`${t('admin.importDetail.title')}${task ? ` #${task.id}` : ''}`"
      :description="task?.filename"
    >
      <template #meta>
        <RouterLink to="/imports" class="admin-link mt-2 inline-block" data-testid="import-detail-back">
          ← {{ t("admin.importDetail.back") }}
        </RouterLink>
      </template>
      <template #actions>
        <Button
          v-if="canRetry"
          data-testid="import-detail-retry"
          :disabled="retryMutation.isPending.value"
          @click="retryMutation.mutate()"
        >
          {{ t("admin.importDetail.retry") }}
        </Button>
        <Button
          v-if="canCancel"
          data-testid="import-detail-cancel"
          :disabled="cancelMutation.isPending.value"
          @click="cancelMutation.mutate()"
        >
          {{ t("admin.importDetail.cancel") }}
        </Button>
      </template>
    </AdminPageHeader>

    <AdminState
      v-if="detailQuery.isError.value"
      state="error"
      testid="import-detail-error"
      :title="t('admin.importDetail.loadError')"
    />
    <AdminState v-else-if="detailQuery.isPending.value" state="loading" testid="import-detail-loading" />

    <AdminCard v-else-if="task">
      <dl class="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
        <div>
          <dt class="text-xs text-muted-foreground">{{ t("admin.importDetail.filename") }}</dt>
          <dd class="font-mono text-xs">{{ task.filename }}</dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">{{ t("admin.importDetail.type") }}</dt>
          <dd>{{ task.type }}</dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">{{ t("admin.importDetail.status") }}</dt>
          <dd><AdminStatusTag :status="task.status" testid="import-detail-status" /></dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">{{ t("admin.importDetail.celeryStatus") }}</dt>
          <dd>{{ live?.celery_status ?? "—" }}</dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">{{ t("admin.importDetail.processed") }}</dt>
          <dd class="font-mono text-xs">
            {{ live?.processed_records ?? task.processed_records ?? 0 }} /
            {{ live?.total_records ?? task.total_records ?? 0 }}
          </dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">{{ t("admin.importDetail.submittedBy") }}</dt>
          <dd>{{ task.submitted_by ?? "—" }}</dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">{{ t("admin.importDetail.submittedAt") }}</dt>
          <dd class="text-xs">{{ formatDate(task.submitted_at) }}</dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">{{ t("admin.importDetail.completedAt") }}</dt>
          <dd class="text-xs">{{ task.completed_at ? formatDate(task.completed_at) : "—" }}</dd>
        </div>
        <div class="sm:col-span-2">
          <dt class="text-xs text-muted-foreground">{{ t("admin.importDetail.filePath") }}</dt>
          <dd class="break-all font-mono text-xs">{{ task.file_path ?? "—" }}</dd>
        </div>
        <div v-if="live?.error_message || task.error_message" class="sm:col-span-2">
          <dt class="text-xs text-muted-foreground">{{ t("admin.importDetail.errorMessage") }}</dt>
          <dd class="text-destructive" data-testid="import-detail-error-message">
            {{ live?.error_message || task.error_message }}
          </dd>
        </div>
      </dl>

      <!-- Server-reported progress; never advanced on the client. -->
      <div class="mt-5">
        <div class="flex items-center justify-between text-xs text-muted-foreground">
          <span>{{ t("admin.importDetail.progress") }}</span>
          <span class="font-mono">{{ progress }}%</span>
        </div>
        <div class="mt-1 h-2 w-full overflow-hidden rounded-full bg-muted">
          <div
            class="h-full rounded-full bg-primary"
            :class="canCancel ? 'progress-running' : ''"
            :style="{ width: `${progress}%` }"
            role="progressbar"
            :aria-valuenow="progress"
            aria-valuemin="0"
            aria-valuemax="100"
          />
        </div>
      </div>
    </AdminCard>
  </div>
</template>

<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue } from "vue";
import { useRoute } from "vue-router";

import { adminImportsApi, type ImportLiveStatus } from "@soymutdb/api-client";
import { formatDate } from "@soymutdb/shared/format";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
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
const progress = computed(
  () => Math.min(100, Math.max(0, live.value?.progress ?? task.value?.progress ?? 0)),
);

const ACTIVE_STATUSES = ["uploading", "validating", "ingesting", "queued", "running"];
const canRetry = computed(() => task.value?.status === "failed");
const canCancel = computed(() => ACTIVE_STATUSES.includes(task.value?.status ?? ""));

function invalidate(): void {
  void queryClient.invalidateQueries({ queryKey: ["admin", "imports"] });
}

const retryMutation = useMutation({
  mutationFn: () => adminImportsApi.retry(taskId.value),
  onSuccess: invalidate,
});
const cancelMutation = useMutation({
  mutationFn: () => adminImportsApi.cancel(taskId.value),
  onSuccess: invalidate,
});
</script>
