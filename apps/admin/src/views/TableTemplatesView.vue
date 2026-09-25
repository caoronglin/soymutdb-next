<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, reactive, ref, toValue } from "vue";

import {
  createTableViewTemplate,
  deleteTableViewTemplate,
  listTableViewTemplates,
  updateTableViewTemplate,
  TABLE_KINDS,
  type TableColumn,
  type TableKind,
  type TableViewTemplate,
} from "@soymutdb/api-client";
import { Button, ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Table-view templates.
 *
 * This is the console half of the configurable tables: an operator picks which
 * columns a portal table renders, in which order, and saves that as a template
 * scoped to one species / site variant / release. The portal resolves the same
 * template at request time (docs/dev/configurable-table-views.md).
 *
 * The cross-assembly homolog columns are offered but never pre-selected: a
 * deployment that has not imported those crosswalk rows would otherwise show an
 * empty column that reads as "no observation".
 */
const queryClient = useQueryClient();
const kind = ref<TableKind>("mutation_sites");
const species = ref("Glycine max");
const siteVariant = ref<"external" | "internal">("external");
const selectedId = ref<number | null>(null);
const errorMessage = ref("");
const draftName = ref("");
const draftColumns = ref<TableColumn[]>([]);
const draftActions = reactive({ jbrowse: true, genome_preview: false });

/** The columns an operator can add, per table kind. */
const CANDIDATES: Record<TableKind, Array<{ key: string; label: string }>> = {
  mutation_sites: [
    { key: "mutant_line_name", label: "株系 / Mutant line" },
    { key: "mutation_system", label: "突变体系（株系母+位置）" },
    { key: "chromosome", label: "染色体号" },
    { key: "position", label: "位点" },
    { key: "confidence", label: "可信度" },
    { key: "gene_id", label: "基因号" },
    { key: "feature", label: "特征" },
    { key: "available", label: "可获得" },
    { key: "homolog:W82_V2", label: "W82_V2（跨组装同源）" },
    { key: "homolog:W82_V4", label: "W82_V4（跨组装同源）" },
    { key: "homolog:DN53_V1", label: "DN53_V1（跨物种同源）" },
  ],
  variants: [
    { key: "variant_id", label: "Variant ID" },
    { key: "chromosome", label: "染色体号" },
    { key: "position", label: "位点" },
    { key: "ref", label: "参考等位" },
    { key: "alt", label: "替代等位" },
    { key: "variant_type", label: "类型" },
    { key: "impact", label: "影响" },
    { key: "gene_id", label: "基因号" },
  ],
  genes: [
    { key: "assembly_name", label: "基因组版本 / Genome version" },
    { key: "chromosome", label: "染色体号" },
    { key: "position", label: "位点" },
    { key: "variant_count", label: "突变特征 / Mutation feature" },
    { key: "gene_id", label: "基因号" },
  ],
  mutant_lines: [
    { key: "public_id", label: "株系" },
    { key: "name", label: "名称" },
    { key: "mutagen", label: "诱变剂" },
    { key: "cultivar", label: "品种" },
    { key: "generation", label: "世代" },
  ],
};

const query = useQuery({
  queryKey: computed(() => ["admin", "table-templates", kind.value]),
  queryFn: () => listTableViewTemplates({ kind: kind.value }),
  staleTime: 15_000,
});

const templates = computed<TableViewTemplate[]>(() => toValue(query.data)?.items ?? []);
const candidates = computed(() => CANDIDATES[kind.value] ?? []);

function selectTemplate(template: TableViewTemplate) {
  selectedId.value = template.id;
  draftName.value = template.name;
  draftColumns.value = template.columns.map((column) => ({ ...column }));
  draftActions.jbrowse = template.actions.jbrowse;
  draftActions.genome_preview = template.actions.genome_preview;
}

function startNew() {
  selectedId.value = null;
  draftName.value = "";
  // The default is the built-in order for this kind, with the homolog columns
  // absent: an operator opts into those explicitly.
  draftColumns.value = candidates.value
    .filter((candidate) => !candidate.key.startsWith("homolog:"))
    .map((candidate) => ({
      key: candidate.key,
      label_zh: candidate.label,
      label_en: candidate.label,
      visible: true,
    }));
  draftActions.jbrowse = true;
  draftActions.genome_preview = kind.value === "mutation_sites";
}

function addColumn(key: string) {
  const candidate = candidates.value.find((item) => item.key === key);
  if (!candidate) return;
  draftColumns.value.push({
    key: candidate.key,
    label_zh: candidate.label,
    label_en: candidate.label,
    visible: true,
  });
}

function move(index: number, delta: number) {
  const next = index + delta;
  if (next < 0 || next >= draftColumns.value.length) return;
  const columns = [...draftColumns.value];
  const [moved] = columns.splice(index, 1);
  columns.splice(next, 0, moved as TableColumn);
  draftColumns.value = columns;
}

const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin", "table-templates"] });

const saveMutation = useMutation({
  mutationFn: () => {
    const payload = {
      name: draftName.value.trim() || `${kind.value} template`,
      columns: draftColumns.value,
      actions: { ...draftActions },
    };
    return selectedId.value
      ? updateTableViewTemplate(selectedId.value, payload)
      : createTableViewTemplate({
          kind: kind.value,
          species: species.value,
          site_variant: siteVariant.value,
          ...payload,
        });
  },
  onSuccess: () => void invalidate(),
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const promoteMutation = useMutation({
  mutationFn: (id: number) => updateTableViewTemplate(id, { is_default: true }),
  onSuccess: () => void invalidate(),
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const deleteMutation = useMutation({
  mutationFn: (id: number) => deleteTableViewTemplate(id),
  onSuccess: () => void invalidate(),
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div>
      <h1 class="text-xl font-semibold">{{ t("admin.tableViews") }}</h1>
      <p class="mt-1 max-w-3xl text-sm opacity-70">{{ t("admin.tableViewsHint") }}</p>

      <div class="mt-4 flex flex-wrap items-end gap-3">
        <label class="text-sm opacity-70">
          {{ t("admin.table") }}
          <select v-model="kind" class="ms-2 rounded-md border bg-background px-2 py-1.5" data-testid="templates-kind">
            <option v-for="value in TABLE_KINDS" :key="value" :value="value">{{ value }}</option>
          </select>
        </label>
        <label class="text-sm opacity-70">
          {{ t("admin.species") }}
          <select v-model="species" class="ms-2 rounded-md border bg-background px-2 py-1.5" data-testid="templates-species">
            <option value="Glycine max">Glycine max</option>
            <option value="Zea mays">Zea mays</option>
          </select>
        </label>
        <label class="text-sm opacity-70">
          {{ t("admin.siteVariant") }}
          <select v-model="siteVariant" class="ms-2 rounded-md border bg-background px-2 py-1.5" data-testid="templates-variant">
            <option value="external">external</option>
            <option value="internal">internal</option>
          </select>
        </label>
        <Button size="small" data-testid="templates-new" @click="startNew">{{ t("admin.newTemplate") }}</Button>
      </div>

      <p v-if="query.isPending.value" class="mt-4 text-sm opacity-70">{{ t("common.loading") }}</p>
      <p v-else-if="query.isError.value" data-testid="templates-error" class="mt-4 text-sm text-red-700">
        {{ t("common.errorDescription") }}
      </p>
      <p v-else-if="templates.length === 0" data-testid="templates-empty" class="mt-4 text-sm opacity-70">
        {{ t("admin.noTemplates") }}
      </p>
      <table v-else class="mt-4 w-full text-sm" data-testid="templates-table">
        <thead class="text-left opacity-60">
          <tr>
            <th scope="col" class="py-2">{{ t("admin.templateName") }}</th>
            <th scope="col" class="py-2">{{ t("admin.columns") }}</th>
            <th scope="col" class="py-2">{{ t("common.status") }}</th>
            <th scope="col" class="py-2">{{ t("common.actions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="template in templates" :key="template.id" class="border-t" data-testid="template-row">
            <td class="py-2">{{ template.name }}</td>
            <td class="py-2 font-mono text-xs">
              {{ template.columns.filter((column) => column.visible).map((column) => column.key).join(", ") }}
            </td>
            <td class="py-2">
              <Tag v-if="template.is_default" color="green">default</Tag>
              <Tag v-if="template.release_id" color="gold">release {{ template.release_id }}</Tag>
            </td>
            <td class="py-2">
              <button type="button" class="underline" :data-testid="'template-edit-' + template.id" @click="selectTemplate(template)">
                {{ t("common.edit") }}
              </button>
              <button
                v-if="!template.is_default"
                type="button"
                class="ms-3 underline"
                :data-testid="'template-default-' + template.id"
                @click="promoteMutation.mutate(template.id)"
              >
                {{ t("admin.setDefault") }}
              </button>
              <button
                type="button"
                class="ms-3 underline text-red-700"
                :data-testid="'template-delete-' + template.id"
                @click="deleteMutation.mutate(template.id)"
              >
                {{ t("common.delete") }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <section class="mt-8 rounded-lg border p-4" data-testid="template-editor">
        <h2 class="text-sm font-medium">{{ selectedId ? t("common.edit") : t("admin.newTemplate") }}</h2>
        <div class="mt-3 grid gap-3">
          <label class="text-sm opacity-70">
            {{ t("admin.templateName") }}
            <input v-model="draftName" class="mt-1 w-full max-w-md rounded-md border bg-background px-2 py-1.5" data-testid="template-name" />
          </label>

          <fieldset class="grid gap-2">
            <legend class="text-sm opacity-70">{{ t("admin.columns") }}</legend>
            <div
              v-for="(column, index) in draftColumns"
              :key="column.key"
              class="flex items-center gap-2 text-sm"
              :data-testid="'template-column-' + column.key"
            >
              <input v-model="column.visible" type="checkbox" :data-testid="'template-visible-' + column.key" />
              <span class="font-mono text-xs">{{ column.key }}</span>
              <button type="button" class="underline" :disabled="index === 0" @click="move(index, -1)">↑</button>
              <button
                type="button"
                class="underline"
                :disabled="index === draftColumns.length - 1"
                @click="move(index, 1)"
              >
                ↓
              </button>
              <button
                type="button"
                class="underline text-red-700"
                @click="draftColumns = draftColumns.filter((_, position) => position !== index)"
              >
                ×
              </button>
            </div>
          </fieldset>

          <div class="flex flex-wrap gap-2">
            <button
              v-for="candidate in candidates.filter((item) => !draftColumns.some((column) => column.key === item.key))"
              :key="candidate.key"
              type="button"
              class="rounded-md border px-2 py-1 text-xs"
              :data-testid="'template-add-' + candidate.key"
              @click="addColumn(candidate.key)"
            >
              + {{ candidate.label }}
            </button>
          </div>

          <div class="flex items-center gap-4 text-sm">
            <label class="flex items-center gap-2">
              <input v-model="draftActions.jbrowse" type="checkbox" data-testid="template-action-jbrowse" />
              JBrowse 2
            </label>
            <label class="flex items-center gap-2">
              <input v-model="draftActions.genome_preview" type="checkbox" data-testid="template-action-genome" />
              {{ t("admin.genomePreview") }}
            </label>
          </div>

          <p v-if="errorMessage" role="alert" class="text-sm text-red-700" data-testid="templates-save-error">
            {{ errorMessage }}
          </p>
          <div class="flex gap-2">
            <Button
              :disabled="draftColumns.length === 0 || saveMutation.isPending.value"
              data-testid="template-save"
              @click="saveMutation.mutate()"
            >
              {{ t("common.save") }}
            </Button>
          </div>
        </div>
      </section>
    </div>
  </ConfigProvider>
</template>
