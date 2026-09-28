<template>
  <div class="admin-page">
    <AdminPageHeader
      :title="t('admin.instances.title')"
      :description="t('admin.instances.description')"
    >
      <template #meta>
        <div class="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span class="text-muted-foreground">{{ t("admin.instances.context") }}:</span>
          <span class="font-medium" data-testid="instances-current">
            {{ currentInstance?.name ?? "—" }}
          </span>
          <Tag v-if="isRemote" color="gold">{{ t("admin.instances.registrationOnly") }}</Tag>
        </div>
        <p v-if="isRemote" class="mt-2 text-xs text-amber-800" data-testid="instances-remote-disabled">
          {{ t("admin.instances.adminDisabled") }}
        </p>
        <p class="mt-2 text-xs text-muted-foreground" data-testid="instances-api-invariant">
          {{ t("admin.instances.apiInvariant") }}
        </p>
      </template>
      <template #actions>
        <Button type="primary" data-testid="instances-new" @click="openCreate">
          {{ t("admin.instances.create") }}
        </Button>
      </template>
    </AdminPageHeader>

    <p v-if="noticeMessage" class="admin-state" data-testid="instances-notice">
      {{ noticeMessage }}
    </p>
    <p v-if="errorMessage" role="alert" class="admin-state admin-state--error" data-testid="instances-error">
      {{ errorMessage }}
    </p>

    <AdminCard
      v-if="editorOpen"
      :title="editingId === null ? t('admin.instances.create') : t('admin.instances.edit')"
      testid="instance-editor"
    >
      <template #actions>
        <span v-if="editingId !== null" class="font-mono text-xs text-muted-foreground">
          #{{ editingId }}
        </span>
      </template>

      <form class="grid gap-3 sm:grid-cols-2" @submit.prevent="saveMutation.mutate()">
        <label class="admin-field">
          <span>{{ t("admin.instances.code") }}</span>
          <input
            v-model="draft.code"
            type="text"
            required
            :disabled="editingId !== null"
            maxlength="32"
            class="admin-control admin-control--mono"
            data-testid="instance-code"
          />
        </label>
        <label class="admin-field">
          <span>{{ t("admin.instances.name") }}</span>
          <input
            v-model="draft.name"
            type="text"
            required
            maxlength="128"
            class="admin-control"
            data-testid="instance-name"
          />
        </label>
        <label class="admin-field">
          <span>{{ t("admin.instances.species") }}</span>
          <input
            v-model="draft.species"
            type="text"
            required
            maxlength="128"
            class="admin-control"
            data-testid="instance-species"
          />
        </label>
        <label class="admin-field">
          <span>{{ t("admin.instances.apiUrl") }}</span>
          <input
            v-model="draft.api_base_url"
            type="url"
            required
            class="admin-control admin-control--mono"
            data-testid="instance-api-url"
          />
        </label>
        <label class="admin-field">
          <span>{{ t("admin.instances.portalUrl") }}</span>
          <input
            v-model="draft.site_url"
            type="url"
            class="admin-control admin-control--mono"
            data-testid="instance-site-url"
          />
        </label>
        <label class="admin-field">
          <span>{{ t("admin.instances.jbrowseUrl") }}</span>
          <input
            v-model="draft.jbrowse_base_url"
            type="url"
            class="admin-control admin-control--mono"
            data-testid="instance-jbrowse-url"
          />
        </label>
        <label class="admin-field sm:col-span-2">
          <span>{{ t("admin.instances.notes") }}</span>
          <textarea v-model="draft.notes" rows="2" class="admin-control" data-testid="instance-notes" />
        </label>
        <label class="flex items-center gap-2 text-sm">
          <input v-model="draft.is_enabled" type="checkbox" data-testid="instance-enabled" />
          {{ t("admin.instances.enabled") }}
        </label>
        <label v-if="editingId === null" class="flex items-center gap-2 text-sm">
          <input v-model="draft.is_local" type="checkbox" data-testid="instance-local" />
          {{ t("admin.instances.local") }}
        </label>

        <p
          v-if="editorIsLocal"
          class="rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground sm:col-span-2"
          data-testid="instance-local-hint"
        >
          {{ t("admin.instances.localHint") }}
        </p>
        <p
          v-else-if="editingId === null && !draft.is_local"
          class="rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground sm:col-span-2"
          data-testid="instance-remote-hint"
        >
          {{ t("admin.instances.remoteHint") }}
        </p>
        <p
          class="rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground sm:col-span-2"
          data-testid="instance-target-note"
        >
          {{ t("admin.instances.targetNote") }}
        </p>

        <div class="flex gap-2 sm:col-span-2">
          <Button
            type="primary"
            html-type="submit"
            :disabled="saveMutation.isPending.value"
            data-testid="instance-save"
          >
            {{ saveMutation.isPending.value ? t("common.loading") : t("common.save") }}
          </Button>
          <Button html-type="button" data-testid="instance-cancel" @click="closeEditor">
            {{ t("common.cancel") }}
          </Button>
        </div>
      </form>
    </AdminCard>

    <p
      v-if="deleteTarget"
      class="admin-state admin-state--error"
      data-testid="instance-delete-confirm"
    >
      <span class="font-medium">{{ t("admin.instances.deleteConfirmTitle") }}</span>
      <span>{{ t("admin.instances.deleteConfirmBody") }}</span>
      <span class="font-mono text-xs">{{ deleteTarget.name }} · {{ deleteTarget.code }}</span>
      <span class="admin-page-actions mt-1">
        <Button
          type="primary"
          danger
          size="small"
          :disabled="deleteMutation.isPending.value"
          data-testid="instance-delete-confirm-button"
          @click="deleteMutation.mutate(deleteTarget.id)"
        >
          {{ t("common.delete") }}
        </Button>
        <Button size="small" data-testid="instance-delete-cancel" @click="deleteTarget = null">
          {{ t("common.cancel") }}
        </Button>
      </span>
    </p>

    <AdminState v-if="query.isPending.value" state="loading" testid="instances-loading" :rows="4" />
    <AdminState
      v-else-if="query.isError.value"
      state="error"
      testid="instances-load-error"
      :title="t('common.errorDescription')"
    >
      <template #actions>
        <Button size="small" data-testid="instances-retry" @click="query.refetch()">
          {{ t("common.retry") }}
        </Button>
      </template>
    </AdminState>
    <AdminState
      v-else-if="instances.length === 0"
      state="empty"
      testid="instances-empty"
      :title="t('admin.instances.empty')"
    />

    <AdminCard v-else>
      <div class="admin-table-wrap">
        <table class="admin-table" data-testid="instances-table">
          <thead>
            <tr>
              <th scope="col">{{ t("admin.instances.name") }}</th>
              <th scope="col">{{ t("admin.instances.species") }}</th>
              <th scope="col">{{ t("admin.instances.apiUrl") }}</th>
              <th scope="col">{{ t("admin.instances.connection") }}</th>
              <th scope="col">{{ t("admin.instances.lastChecked") }}</th>
              <th scope="col">{{ t("common.actions") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="instance in instances" :key="instance.id" data-testid="instance-row">
              <td>
                <p class="font-medium">{{ instance.name }}</p>
                <p class="font-mono text-xs text-muted-foreground">{{ instance.code }}</p>
                <div class="mt-1 flex flex-wrap gap-1">
                  <Tag v-if="instance.is_local" color="blue">{{ t("admin.instances.local") }}</Tag>
                  <Tag v-if="currentInstance?.code === instance.code" color="green">
                    {{ t("admin.instances.currentFlag") }}
                  </Tag>
                  <Tag v-if="!instance.is_enabled" color="default">
                    {{ t("admin.instances.disabled") }}
                  </Tag>
                </div>
              </td>
              <td>{{ instance.species }}</td>
              <td>
                <span class="font-mono text-xs">{{ instance.api_base_url }}</span>
                <a
                  v-if="safeUrl(instance.portal_base_url ?? instance.site_url)"
                  :href="safeUrl(instance.portal_base_url ?? instance.site_url) ?? undefined"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="admin-link mt-1 block text-xs"
                  :data-testid="'instance-open-' + instance.id"
                >
                  {{ t("admin.instances.openPortal") }}
                </a>
              </td>
              <td>
                <AdminStatusTag
                  :status="instance.connection_state"
                  :label="stateLabel(instance.connection_state)"
                />
              </td>
              <td class="text-xs text-muted-foreground">{{ formatDate(instance.last_checked_at) }}</td>
              <td>
                <div class="admin-row-actions">
                  <Button
                    size="small"
                    html-type="button"
                    :data-testid="'instance-edit-' + instance.id"
                    @click="openEdit(instance)"
                  >
                    {{ t("common.edit") }}
                  </Button>
                  <Button
                    size="small"
                    html-type="button"
                    :disabled="currentInstance?.code === instance.code"
                    :data-testid="'instance-select-' + instance.id"
                    @click="setCurrent(instance)"
                  >
                    {{
                      currentInstance?.code === instance.code
                        ? t("admin.instances.currentFlag")
                        : t("admin.instances.setCurrent")
                    }}
                  </Button>
                  <Button
                    size="small"
                    html-type="button"
                    :disabled="checkingId === instance.id"
                    :data-testid="'instance-check-' + instance.id"
                    @click="checkHealth(instance)"
                  >
                    {{
                      checkingId === instance.id
                        ? t("admin.instances.checking")
                        : t("admin.instances.checkConnection")
                    }}
                  </Button>
                  <Button
                    size="small"
                    html-type="button"
                    :disabled="instance.is_local"
                    :title="instance.is_local ? t('admin.instances.localHint') : undefined"
                    :data-testid="'instance-delete-' + instance.id"
                    @click="deleteTarget = instance"
                  >
                    {{ t("common.delete") }}
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </AdminCard>
  </div>
</template>

<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, reactive, ref, toValue } from "vue";

import {
  checkSpeciesInstanceHealth,
  createSpeciesInstance,
  deleteSpeciesInstance,
  listSpeciesInstances,
  updateSpeciesInstance,
  type SpeciesInstance,
} from "@soymutdb/api-client";
import { formatDate } from "@soymutdb/shared/format";
import { Button, Tag } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
import { t } from "../lib/i18n";
import { useInstanceContext } from "../lib/instance-context";

/**
 * Species instance registry.
 *
 * This page manages the console's *registration* rows: which SoyMutDB
 * deployments exist, where their API and portal live, and whether they answer
 * a liveness probe. It is deliberately not a remote administration channel.
 * Remote rows stay `registration_only`; the bounded probe implemented in
 * apps/api/app/services/species_instance_health_service.py is the single
 * network call this page can make against a peer, and it never forwards the
 * operator's credentials or biology.
 */
const queryClient = useQueryClient();
const { currentInstance, isRemote, selectInstance } = useInstanceContext();
const errorMessage = ref("");
const noticeMessage = ref("");
const editorOpen = ref(false);
const editingId = ref<number | null>(null);
const editorIsLocal = ref(false);
const deleteTarget = ref<SpeciesInstance | null>(null);
const checkingId = ref<number | null>(null);

const draft = reactive({
  code: "",
  name: "",
  species: "Glycine max",
  api_base_url: "",
  site_url: "",
  jbrowse_base_url: "",
  notes: "",
  is_enabled: true,
  is_local: false,
});

const query = useQuery({
  queryKey: ["admin", "species-instances"],
  queryFn: listSpeciesInstances,
  retry: false,
});

const instances = computed<SpeciesInstance[]>(() => toValue(query.data)?.items ?? []);

function resetDraft(): void {
  draft.code = "";
  draft.name = "";
  draft.species = "Glycine max";
  draft.api_base_url = "";
  draft.site_url = "";
  draft.jbrowse_base_url = "";
  draft.notes = "";
  draft.is_enabled = true;
  draft.is_local = false;
}

function openCreate(): void {
  editingId.value = null;
  editorIsLocal.value = false;
  resetDraft();
  editorOpen.value = true;
  errorMessage.value = "";
  noticeMessage.value = "";
}

function openEdit(instance: SpeciesInstance): void {
  editingId.value = instance.id;
  editorIsLocal.value = instance.is_local;
  draft.code = instance.code;
  draft.name = instance.name;
  draft.species = instance.species;
  draft.api_base_url = instance.api_base_url;
  draft.site_url = instance.portal_base_url ?? instance.site_url ?? "";
  draft.jbrowse_base_url = instance.jbrowse_base_url ?? "";
  draft.notes = instance.notes ?? "";
  draft.is_enabled = instance.is_enabled;
  draft.is_local = instance.is_local;
  editorOpen.value = true;
  errorMessage.value = "";
  noticeMessage.value = "";
}

function closeEditor(): void {
  editorOpen.value = false;
  editingId.value = null;
}

const saveMutation = useMutation({
  mutationFn: () => {
    const fields = {
      name: draft.name.trim(),
      species: draft.species.trim(),
      api_base_url: draft.api_base_url.trim(),
      site_url: draft.site_url.trim() || null,
      jbrowse_base_url: draft.jbrowse_base_url.trim() || null,
      notes: draft.notes.trim() || null,
      is_enabled: draft.is_enabled,
    };
    // `code` and `is_local` are registration-time identities: the update endpoint
    // does not accept them, so an existing row keeps both.
    return editingId.value === null
      ? createSpeciesInstance({ code: draft.code.trim(), is_local: draft.is_local, ...fields })
      : updateSpeciesInstance(editingId.value, fields);
  },
  onSuccess: () => {
    closeEditor();
    noticeMessage.value = t("admin.instances.saveSuccess");
    errorMessage.value = "";
    void queryClient.invalidateQueries({ queryKey: ["admin", "species-instances"] });
  },
  onError: () => {
    noticeMessage.value = "";
    errorMessage.value = t("admin.instances.saveError");
  },
});

const deleteMutation = useMutation({
  mutationFn: (id: number) => deleteSpeciesInstance(id),
  onSuccess: () => {
    deleteTarget.value = null;
    noticeMessage.value = t("admin.instances.deleteSuccess");
    errorMessage.value = "";
    void queryClient.invalidateQueries({ queryKey: ["admin", "species-instances"] });
  },
  onError: () => {
    deleteTarget.value = null;
    noticeMessage.value = "";
    errorMessage.value = t("admin.instances.deleteError");
  },
});

const healthMutation = useMutation({
  mutationFn: (id: number) => checkSpeciesInstanceHealth(id),
  onSuccess: () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "species-instances"] });
  },
  onError: () => {
    noticeMessage.value = "";
    errorMessage.value = t("admin.instances.healthError");
  },
});

function setCurrent(instance: SpeciesInstance): void {
  selectInstance(instance.code);
}

function checkHealth(instance: SpeciesInstance): void {
  checkingId.value = instance.id;
  healthMutation.mutate(instance.id, {
    onSettled: () => {
      if (checkingId.value === instance.id) checkingId.value = null;
    },
  });
}

/** Only absolute HTTP(S) URLs become links; anything else stays plain text. */
function safeUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? value : null;
  } catch {
    return null;
  }
}

function stateLabel(state: SpeciesInstance["connection_state"]): string {
  if (state === "healthy") return t("admin.instances.healthy");
  if (state === "unhealthy") return t("admin.instances.unreachable");
  if (state === "disabled") return t("admin.instances.disabled");
  if (state === "unconfigured") return t("admin.instances.unconfigured");
  return t("common.unknown");
}
</script>
