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
import { Button, ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

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
  staleTime: 30_000,
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
    // `code` and `is_local` are registration-time identities: the update
    // endpoint does not accept them, so an existing row keeps both.
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

function stateColor(state: SpeciesInstance["connection_state"]): string {
  if (state === "healthy") return "green";
  if (state === "unhealthy") return "red";
  if (state === "unconfigured") return "gold";
  return "default";
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div>
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 class="text-xl font-semibold">{{ t("admin.instances.title") }}</h1>
          <p class="mt-1 max-w-2xl text-sm opacity-70">{{ t("admin.instances.description") }}</p>
        </div>
        <Button type="primary" data-testid="instances-new" @click="openCreate">
          {{ t("admin.instances.create") }}
        </Button>
      </div>

      <div
        class="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs"
      >
        <span class="opacity-70">{{ t("admin.instances.context") }}:</span>
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

      <p
        v-if="noticeMessage"
        data-testid="instances-notice"
        class="mt-4 rounded-md border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-800"
      >
        {{ noticeMessage }}
      </p>
      <p
        v-if="errorMessage"
        data-testid="instances-error"
        class="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
      >
        {{ errorMessage }}
      </p>

      <section
        v-if="editorOpen"
        class="mt-4 rounded-lg border border-border bg-card p-4"
        data-testid="instance-editor"
      >
        <h2 class="text-sm font-medium">
          {{ editingId === null ? t("admin.instances.create") : t("admin.instances.edit") }}
          <span v-if="editingId !== null" class="ms-2 font-mono text-xs opacity-70">
            #{{ editingId }}
          </span>
        </h2>

        <form class="mt-3 grid gap-3 sm:grid-cols-2" @submit.prevent="saveMutation.mutate()">
          <label class="text-sm">
            <span class="opacity-70">{{ t("admin.instances.code") }}</span>
            <input
              v-model="draft.code"
              type="text"
              required
              :disabled="editingId !== null"
              maxlength="32"
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs disabled:opacity-60"
              data-testid="instance-code"
            />
          </label>
          <label class="text-sm">
            <span class="opacity-70">{{ t("admin.instances.name") }}</span>
            <input
              v-model="draft.name"
              type="text"
              required
              maxlength="128"
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              data-testid="instance-name"
            />
          </label>
          <label class="text-sm">
            <span class="opacity-70">{{ t("admin.instances.species") }}</span>
            <input
              v-model="draft.species"
              type="text"
              required
              maxlength="128"
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              data-testid="instance-species"
            />
          </label>
          <label class="text-sm">
            <span class="opacity-70">{{ t("admin.instances.apiUrl") }}</span>
            <input
              v-model="draft.api_base_url"
              type="url"
              required
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs"
              data-testid="instance-api-url"
            />
          </label>
          <label class="text-sm">
            <span class="opacity-70">{{ t("admin.instances.portalUrl") }}</span>
            <input
              v-model="draft.site_url"
              type="url"
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs"
              data-testid="instance-site-url"
            />
          </label>
          <label class="text-sm">
            <span class="opacity-70">{{ t("admin.instances.jbrowseUrl") }}</span>
            <input
              v-model="draft.jbrowse_base_url"
              type="url"
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs"
              data-testid="instance-jbrowse-url"
            />
          </label>
          <label class="text-sm sm:col-span-2">
            <span class="opacity-70">{{ t("admin.instances.notes") }}</span>
            <textarea
              v-model="draft.notes"
              rows="2"
              class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              data-testid="instance-notes"
            />
          </label>
          <label class="flex items-center gap-2 text-sm">
            <input
              v-model="draft.is_enabled"
              type="checkbox"
              data-testid="instance-enabled"
            />
            {{ t("admin.instances.enabled") }}
          </label>
          <label v-if="editingId === null" class="flex items-center gap-2 text-sm">
            <input
              v-model="draft.is_local"
              type="checkbox"
              data-testid="instance-local"
            />
            {{ t("admin.instances.local") }}
          </label>

          <p
            v-if="editorIsLocal"
            class="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-muted-foreground sm:col-span-2"
            data-testid="instance-local-hint"
          >
            {{ t("admin.instances.localHint") }}
          </p>
          <p
            v-else-if="editingId === null && !draft.is_local"
            class="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-muted-foreground sm:col-span-2"
            data-testid="instance-remote-hint"
          >
            {{ t("admin.instances.remoteHint") }}
          </p>
          <p
            class="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-muted-foreground sm:col-span-2"
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
      </section>

      <section
        v-if="deleteTarget"
        class="mt-4 rounded-lg border border-red-300 bg-red-50 p-4"
        data-testid="instance-delete-confirm"
      >
        <p class="text-sm font-medium text-red-800">{{ t("admin.instances.deleteConfirmTitle") }}</p>
        <p class="mt-1 text-sm text-red-700">{{ t("admin.instances.deleteConfirmBody") }}</p>
        <p class="mt-1 font-mono text-xs text-red-700">
          {{ deleteTarget.name }} · {{ deleteTarget.code }}
        </p>
        <div class="mt-2 flex gap-2">
          <Button
            type="primary"
            danger
            :disabled="deleteMutation.isPending.value"
            data-testid="instance-delete-confirm-button"
            @click="deleteMutation.mutate(deleteTarget.id)"
          >
            {{ t("common.delete") }}
          </Button>
          <Button html-type="button" data-testid="instance-delete-cancel" @click="deleteTarget = null">
            {{ t("common.cancel") }}
          </Button>
        </div>
      </section>

      <p v-if="query.isPending.value" data-testid="instances-loading" class="mt-4 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <p
        v-else-if="query.isError.value"
        data-testid="instances-load-error"
        class="mt-4 text-sm text-red-700"
      >
        {{ t("common.errorDescription") }}
      </p>
      <p
        v-else-if="instances.length === 0"
        data-testid="instances-empty"
        class="mt-4 text-sm opacity-70"
      >
        {{ t("admin.instances.empty") }}
      </p>
      <table v-else class="mt-4 w-full text-sm" data-testid="instances-table">
        <thead class="text-left opacity-60">
          <tr>
            <th scope="col" class="py-2">{{ t("admin.instances.name") }}</th>
            <th scope="col" class="py-2">{{ t("admin.instances.species") }}</th>
            <th scope="col" class="py-2">{{ t("admin.instances.apiUrl") }}</th>
            <th scope="col" class="py-2">{{ t("admin.instances.connection") }}</th>
            <th scope="col" class="py-2">{{ t("admin.instances.lastChecked") }}</th>
            <th scope="col" class="py-2">{{ t("common.actions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="instance in instances"
            :key="instance.id"
            class="border-t border-border align-top"
            data-testid="instance-row"
          >
            <td class="py-2">
              <p class="font-medium">{{ instance.name }}</p>
              <p class="font-mono text-xs opacity-70">{{ instance.code }}</p>
              <Tag v-if="instance.is_local" color="blue">{{ t("admin.instances.local") }}</Tag>
              <Tag v-if="currentInstance?.code === instance.code" color="green">
                {{ t("admin.instances.currentFlag") }}
              </Tag>
              <Tag v-if="!instance.is_enabled" color="default">{{ t("admin.instances.disabled") }}</Tag>
            </td>
            <td class="py-2">{{ instance.species }}</td>
            <td class="py-2">
              <span class="font-mono text-xs">{{ instance.api_base_url }}</span>
              <a
                v-if="safeUrl(instance.portal_base_url ?? instance.site_url)"
                :href="safeUrl(instance.portal_base_url ?? instance.site_url) ?? undefined"
                target="_blank"
                rel="noopener noreferrer"
                class="mt-1 block text-xs text-primary underline"
                :data-testid="'instance-open-' + instance.id"
              >
                {{ t("admin.instances.openPortal") }}
              </a>
            </td>
            <td class="py-2">
              <Tag :color="stateColor(instance.connection_state)">
                {{ stateLabel(instance.connection_state) }}
              </Tag>
            </td>
            <td class="py-2 text-xs opacity-70">{{ formatDate(instance.last_checked_at) }}</td>
            <td class="py-2">
              <div class="flex flex-wrap gap-2">
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
                  {{ currentInstance?.code === instance.code ? t("admin.instances.currentFlag") : t("admin.instances.setCurrent") }}
                </Button>
                <Button
                  size="small"
                  html-type="button"
                  :disabled="!instance.is_enabled || checkingId === instance.id"
                  :data-testid="'instance-check-' + instance.id"
                  @click="checkHealth(instance)"
                >
                  {{ checkingId === instance.id ? t("admin.instances.checking") : t("admin.instances.checkConnection") }}
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
  </ConfigProvider>
</template>
