<template>
  <div class="admin-page">
    <AdminPageHeader :title="t('admin.settings')">
      <template #meta>
        <RouterLink
          to="/settings/brand"
          class="admin-link mt-2 inline-block"
          data-testid="settings-brand-link"
        >
          {{ t("admin.brand.title") }}
        </RouterLink>
      </template>
    </AdminPageHeader>

    <AdminState v-if="schemaQuery.isPending.value" state="loading" testid="settings-loading" />
    <AdminState
      v-else-if="schemaQuery.isError.value"
      state="error"
      testid="settings-error"
      :title="t('common.errorDescription')"
    >
      <template #actions>
        <Button size="small" data-testid="settings-retry" @click="schemaQuery.refetch()">
          {{ t("common.retry") }}
        </Button>
      </template>
    </AdminState>

    <AdminState
      v-else-if="missingSection"
      state="error"
      testid="settings-section-missing"
      :title="t('admin.legacyUnavailable.sectionMissingTitle')"
      :description="
        t('admin.legacyUnavailable.sectionMissingDescription', { section: missingSection })
      "
    >
      <p class="mt-1 rounded-md border border-border bg-muted px-3 py-2 font-mono text-xs">
        {{ t("admin.legacyUnavailable.sectionMissingPath", { path: route.path, section: missingSection }) }}
      </p>
      <template #actions>
        <RouterLink to="/settings" class="admin-link">{{ t("admin.settings") }}</RouterLink>
      </template>
    </AdminState>

    <div v-else class="grid gap-6 lg:grid-cols-[200px_1fr]">
      <AdminCard class="self-start">
        <nav class="grid gap-1" :aria-label="t('admin.settingsSections')">
          <button
            v-for="section in sections"
            :key="section.id"
            type="button"
            class="rounded-md px-2.5 py-1.5 text-left text-sm transition-colors"
            :class="
              section.id === activeSection
                ? 'bg-primary/10 font-medium text-primary'
                : 'text-muted-foreground hover:bg-muted'
            "
            :aria-current="section.id === activeSection ? 'true' : undefined"
            :data-testid="'settings-section-' + section.id"
            @click="selectSection(section.id)"
          >
            {{ section.id }}
          </button>
        </nav>
      </AdminCard>

      <AdminCard :title="activeSection">
        <template #actions>
          <span v-if="documentQuery.data.value" class="text-xs text-muted-foreground">
            v{{ documentQuery.data.value.version }}
          </span>
        </template>

        <AdminState
          v-if="documentQuery.isPending.value"
          state="loading"
          testid="settings-section-loading"
        />
        <AdminState
          v-else-if="documentQuery.isError.value"
          state="error"
          testid="settings-section-error"
          :title="t('common.errorDescription')"
        />
        <form v-else class="grid gap-3" @submit.prevent="saveMutation.mutate()">
          <label v-for="field in currentSection?.fields ?? []" :key="field.key" class="admin-field">
            <span>
              <span class="font-mono text-xs">{{ field.key }}</span>
              <span v-if="field.redaction === 'omit'" class="ms-1 text-[11px] text-muted-foreground">
                ({{ t("admin.settingsSecret") }})
              </span>
            </span>
            <select
              v-if="field.kind === 'enum' && field.allowed_values.length"
              v-model="draft[field.key]"
              class="admin-control admin-control--mono"
              :data-testid="'settings-field-' + field.key"
            >
              <option v-for="option in field.allowed_values" :key="option" :value="option">
                {{ option }}
              </option>
            </select>
            <select
              v-else-if="field.kind === 'boolean'"
              v-model="draft[field.key]"
              class="admin-control admin-control--mono"
              :data-testid="'settings-field-' + field.key"
            >
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
            <input
              v-else
              v-model="draft[field.key]"
              :type="field.redaction === 'omit' ? 'password' : 'text'"
              class="admin-control admin-control--mono"
              :data-testid="'settings-field-' + field.key"
            />
          </label>

          <p
            v-if="errorMessage"
            role="alert"
            class="admin-state admin-state--error"
            data-testid="settings-save-error"
          >
            {{ errorMessage }}
          </p>
          <p
            v-if="savedMessage"
            role="status"
            class="admin-state"
            data-testid="settings-saved"
          >
            {{ savedMessage }}
          </p>

          <div>
            <Button
              type="primary"
              html-type="submit"
              :disabled="saveMutation.isPending.value"
              data-testid="settings-save"
            >
              {{ t("common.save") }}
            </Button>
          </div>
        </form>
      </AdminCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, reactive, ref, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { adminSettingsApi, type SettingValue } from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import { t } from "../lib/i18n";

/**
 * Site settings.
 *
 * The form is generated from the backend's schema rather than a hand-written
 * list, so a section that gains a field appears here without a console release
 * and a removed field cannot leave a stale input behind. Saving sends the whole
 * section with the revision the form was loaded from: the API rejects a save
 * whose revision is stale, which is what stops two operators from overwriting
 * each other.
 */
const queryClient = useQueryClient();
const route = useRoute();
const router = useRouter();
const activeSection = ref("");
const missingSection = ref("");
const draft = reactive<Record<string, string>>({});
const errorMessage = ref("");
const savedMessage = ref("");

const schemaQuery = useQuery({
  queryKey: ["admin", "settings", "schema"],
  queryFn: () => adminSettingsApi.schema(),
  staleTime: 5 * 60_000,
});

const sections = computed(() =>
  Object.entries(toValue(schemaQuery.data)?.sections ?? {}).map(([id, section]) => ({
    id,
    fields: Object.entries(section.fields).map(([key, field]) => ({ key, ...field })),
  })),
);

// The active section is shareable: `?section=` selects a registered section and
// the sidebar writes it back, so a legacy deep link opens the right editor
// instead of the first one.
watch(
  [sections, () => route.query.section],
  ([value, requested]) => {
    const wanted = typeof requested === "string" ? requested : "";
    if (wanted && value.some((section) => section.id === wanted)) {
      missingSection.value = "";
      activeSection.value = wanted;
      return;
    }
    if (wanted && value.length > 0) {
      // Requested but not registered: falling back to the first section would
      // read as if the requested editor had opened, so render an explicit
      // unavailable state instead (path + reason + link).
      missingSection.value = wanted;
      activeSection.value = "";
      return;
    }
    missingSection.value = "";
    if (!activeSection.value && value.length > 0) activeSection.value = value[0]!.id;
  },
  { immediate: true },
);

function selectSection(id: string): void {
  activeSection.value = id;
  void router.replace({ path: route.path, query: { ...route.query, section: id } });
}

const currentSection = computed(() =>
  sections.value.find((section) => section.id === activeSection.value),
);

const documentQuery = useQuery({
  queryKey: computed(() => ["admin", "settings", activeSection.value]),
  queryFn: () => adminSettingsApi.get(activeSection.value),
  enabled: computed(() => Boolean(activeSection.value)),
});

watch(
  [() => toValue(documentQuery.data), currentSection],
  ([document]) => {
    if (!document) return;
    for (const key of Object.keys(draft)) delete draft[key];
    for (const [key, value] of Object.entries(document.values ?? {})) {
      draft[key] = value === null || value === undefined ? "" : String(value);
    }
    savedMessage.value = "";
    errorMessage.value = "";
  },
  { immediate: true },
);

/** Coerce a form string back to the type the schema declares. */
function coerce(kind: string, raw: string): SettingValue {
  if (kind === "boolean") return raw === "true";
  if (kind === "integer") return Number(raw);
  return raw;
}

const saveMutation = useMutation({
  mutationFn: () => {
    const values: Record<string, SettingValue> = {};
    for (const field of currentSection.value?.fields ?? []) {
      values[field.key] = coerce(field.kind, draft[field.key] ?? "");
    }
    return adminSettingsApi.patch(
      activeSection.value,
      toValue(documentQuery.data)?.version ?? 0,
      values,
    );
  },
  onSuccess: () => {
    savedMessage.value = t("common.success");
    errorMessage.value = "";
    void queryClient.invalidateQueries({ queryKey: ["admin", "settings"] });
  },
  onError: () => {
    // A rejected save is usually a stale revision, or a value the schema
    // rejects; either way the form keeps its values so the operator can retry.
    savedMessage.value = "";
    errorMessage.value = t("common.errorDescription");
  },
});
</script>
