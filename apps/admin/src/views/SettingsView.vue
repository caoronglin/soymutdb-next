<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, reactive, ref, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { adminSettingsApi, type SettingValue } from "@soymutdb/api-client";
import { Button, ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

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

// The active section is shareable: `?section=` selects a registered section
// and the sidebar writes it back, so a legacy deep link (e.g. one that lands on
// the security section) opens the right editor instead of the first one.
watch(
  [sections, () => route.query.section],
  ([value, requested]) => {
    const wanted = typeof requested === "string" ? requested : "";
    if (wanted && value.some((section) => section.id === wanted)) {
      activeSection.value = wanted;
      return;
    }
    if (!activeSection.value && value.length > 0) activeSection.value = value[0]!.id;
  },
  { immediate: true },
);

function selectSection(id: string): void {
  activeSection.value = id;
  void router.replace({ path: route.path, query: { ...route.query, section: id } });
}

const currentSection = computed(() => sections.value.find((section) => section.id === activeSection.value));

const documentQuery = useQuery({
  queryKey: computed(() => ["admin", "settings", activeSection.value]),
  queryFn: () => adminSettingsApi.get(activeSection.value),
  enabled: computed(() => Boolean(activeSection.value)),
  staleTime: 15_000,
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
    return adminSettingsApi.patch(activeSection.value, toValue(documentQuery.data)?.version ?? 0, values);
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

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div>
      <h1 class="text-xl font-semibold">{{ t("admin.settings") }}</h1>
      <RouterLink
        to="/settings/brand"
        class="mt-2 inline-block text-sm text-primary underline"
        data-testid="settings-brand-link"
      >
        {{ t("admin.brand.title") }}
      </RouterLink>

      <p v-if="schemaQuery.isPending.value" class="mt-4 text-sm opacity-70">{{ t("common.loading") }}</p>
      <p v-else-if="schemaQuery.isError.value" data-testid="settings-error" class="mt-4 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <div v-else class="mt-4 grid gap-6 lg:grid-cols-[200px_1fr]">
        <nav class="grid content-start gap-1" :aria-label="t('admin.settingsSections')">
          <button
            v-for="section in sections"
            :key="section.id"
            type="button"
            class="rounded-md px-2 py-1.5 text-left text-sm"
            :class="section.id === activeSection ? 'bg-black/5 font-medium' : 'opacity-70'"
            :data-testid="'settings-section-' + section.id"
            @click="selectSection(section.id)"
          >
            {{ section.id }}
          </button>
        </nav>

        <section class="rounded-lg border p-4">
          <h2 class="text-sm font-medium">
            {{ activeSection }}
            <span v-if="documentQuery.data" class="ms-2 text-xs opacity-70">
              v{{ documentQuery.data.value?.version }}
            </span>
          </h2>
          <p v-if="documentQuery.isPending.value" class="mt-2 text-sm opacity-70">
            {{ t("common.loading") }}
          </p>
          <p v-else-if="documentQuery.isError.value" class="mt-2 text-sm text-red-700">
            {{ t("common.errorDescription") }}
          </p>
          <form v-else class="mt-3 grid gap-3" @submit.prevent="saveMutation.mutate()">
            <label v-for="field in currentSection?.fields ?? []" :key="field.key" class="text-sm opacity-70">
              <span class="font-mono text-xs">{{ field.key }}</span>
              <Tag v-if="field.redaction === 'omit'" color="gold">{{ t("admin.settingsSecret") }}</Tag>
              <select
                v-if="field.kind === 'enum' && field.allowed_values.length"
                v-model="draft[field.key]"
                class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono text-xs"
                :data-testid="'settings-field-' + field.key"
              >
                <option v-for="option in field.allowed_values" :key="option" :value="option">{{ option }}</option>
              </select>
              <select
                v-else-if="field.kind === 'boolean'"
                v-model="draft[field.key]"
                class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono text-xs"
                :data-testid="'settings-field-' + field.key"
              >
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
              <input
                v-else
                v-model="draft[field.key]"
                :type="field.redaction === 'omit' ? 'password' : 'text'"
                class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono text-xs"
                :data-testid="'settings-field-' + field.key"
              />
            </label>
            <p v-if="errorMessage" role="alert" class="text-sm text-red-700" data-testid="settings-save-error">
              {{ errorMessage }}
            </p>
            <p v-if="savedMessage" role="status" class="text-sm text-green-700" data-testid="settings-saved">
              {{ savedMessage }}
            </p>
            <Button html-type="submit" :disabled="saveMutation.isPending.value" data-testid="settings-save">
              {{ t("common.save") }}
            </Button>
          </form>
        </section>
      </div>
    </div>
  </ConfigProvider>
</template>
