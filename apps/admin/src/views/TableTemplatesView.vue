<template>
  <div class="admin-page">
    <AdminPageHeader :title="t('admin.tableViews')" :description="t('admin.tableViewsHint')">
      <template #actions>
        <Button size="small" data-testid="templates-new" @click="startNew">
          {{ t("admin.newTemplate") }}
        </Button>
      </template>
    </AdminPageHeader>

    <form class="admin-toolbar">
      <label class="admin-field">
        {{ t("admin.table") }}
        <select v-model="kind" class="admin-control" data-testid="templates-kind">
          <option v-for="value in TABLE_KINDS" :key="value" :value="value">{{ value }}</option>
        </select>
      </label>
      <label class="admin-field">
        {{ t("admin.species") }}
        <select v-model="species" class="admin-control" data-testid="templates-species">
          <option value="Glycine max">Glycine max</option>
          <option value="Zea mays">Zea mays</option>
        </select>
      </label>
      <label class="admin-field">
        {{ t("admin.siteVariant") }}
        <select v-model="siteVariant" class="admin-control" data-testid="templates-variant">
          <option value="external">external</option>
          <option value="internal">internal</option>
        </select>
      </label>
    </form>

    <AdminState v-if="query.isPending.value" state="loading" testid="templates-loading" />
    <AdminState
      v-else-if="query.isError.value"
      state="error"
      testid="templates-error"
      :title="t('common.errorDescription')"
    >
      <template #actions>
        <Button size="small" @click="query.refetch()">{{ t("common.retry") }}</Button>
      </template>
    </AdminState>
    <AdminState
      v-else-if="templates.length === 0"
      state="empty"
      testid="templates-empty"
      :title="t('admin.noTemplates')"
    />

    <AdminCard v-else>
      <div class="admin-table-wrap">
        <table class="admin-table" data-testid="templates-table">
          <thead>
            <tr>
              <th scope="col">{{ t("admin.templateName") }}</th>
              <th scope="col">{{ t("admin.columns") }}</th>
              <th scope="col">{{ t("common.status") }}</th>
              <th scope="col">{{ t("common.actions") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="template in templates" :key="template.id" data-testid="template-row">
              <td>{{ template.name }}</td>
              <td class="font-mono text-xs">
                {{
                  template.columns
                    .filter((column) => column.visible)
                    .map((column) => column.key)
                    .join(", ")
                }}
              </td>
              <td>
                <AdminStatusTag v-if="template.is_default" status="default" />
                <span v-if="template.release_id" class="ms-1 text-xs text-muted-foreground">
                  release {{ template.release_id }}
                </span>
              </td>
              <td>
                <div class="admin-row-actions">
                  <button
                    type="button"
                    class="admin-link"
                    :data-testid="'template-edit-' + template.id"
                    @click="selectTemplate(template)"
                  >
                    {{ t("common.edit") }}
                  </button>
                  <button
                    v-if="!template.is_default"
                    type="button"
                    class="admin-link"
                    :data-testid="'template-default-' + template.id"
                    @click="promoteMutation.mutate(template.id)"
                  >
                    {{ t("admin.setDefault") }}
                  </button>
                  <button
                    type="button"
                    class="admin-link admin-link--danger"
                    :data-testid="'template-delete-' + template.id"
                    @click="deleteMutation.mutate(template.id)"
                  >
                    {{ t("common.delete") }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </AdminCard>

    <AdminCard
      :title="selectedId ? t('common.edit') : t('admin.newTemplate')"
      testid="template-editor"
    >
      <div class="grid gap-4">
        <label class="admin-field max-w-md">
          {{ t("admin.templateName") }}
          <input v-model="draftName" class="admin-control" data-testid="template-name" />
        </label>

        <fieldset class="grid gap-2">
          <legend class="admin-field">{{ t("admin.columns") }}</legend>
          <p v-if="draftColumns.length === 0" class="text-xs text-muted-foreground">
            {{ t("admin.noTemplates") }}
          </p>
          <div
            v-for="(column, index) in draftColumns"
            :key="column.key"
            class="flex flex-wrap items-center gap-2 text-sm"
            :data-testid="'template-column-' + column.key"
          >
            <input v-model="column.visible" type="checkbox" :data-testid="'template-visible-' + column.key" />
            <span class="font-mono text-xs">{{ column.key }}</span>
            <button
              type="button"
              class="admin-link"
              :disabled="index === 0"
              :aria-label="`${column.key} up`"
              @click="move(index, -1)"
            >
              ↑
            </button>
            <button
              type="button"
              class="admin-link"
              :disabled="index === draftColumns.length - 1"
              :aria-label="`${column.key} down`"
              @click="move(index, 1)"
            >
              ↓
            </button>
            <button
              type="button"
              class="admin-link admin-link--danger"
              :aria-label="`${column.key} remove`"
              @click="draftColumns = draftColumns.filter((_, position) => position !== index)"
            >
              ×
            </button>
          </div>
        </fieldset>

        <div v-if="availableCandidates.length" class="flex flex-wrap gap-2">
          <button
            v-for="candidate in availableCandidates"
            :key="candidate.key"
            type="button"
            class="rounded-md border border-dashed border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
            :data-testid="'template-add-' + candidate.key"
            @click="addColumn(candidate.key)"
          >
            + {{ candidate.label }}
          </button>
        </div>

        <div class="flex flex-wrap items-center gap-4 text-sm">
          <label class="flex items-center gap-2">
            <input v-model="draftActions.jbrowse" type="checkbox" data-testid="template-action-jbrowse" />
            JBrowse 2
          </label>
          <label class="flex items-center gap-2">
            <input v-model="draftActions.genome_preview" type="checkbox" data-testid="template-action-genome" />
            {{ t("admin.genomePreview") }}
          </label>
        </div>

        <p
          v-if="errorMessage"
          role="alert"
          class="admin-state admin-state--error"
          data-testid="templates-save-error"
        >
          {{ errorMessage }}
        </p>

        <div>
          <Button
            type="primary"
            :disabled="draftColumns.length === 0 || saveMutation.isPending.value"
            data-testid="template-save"
            @click="saveMutation.mutate()"
          >
            {{ t("common.save") }}
          </Button>
        </div>
      </div>
    </AdminCard>
  </div>
</template>

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
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
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
});

const templates = computed<TableViewTemplate[]>(() => toValue(query.data)?.items ?? []);
const candidates = computed(() => CANDIDATES[kind.value] ?? []);
const availableCandidates = computed(() =>
  candidates.value.filter(
    (candidate) => !draftColumns.value.some((column) => column.key === candidate.key),
  ),
);

function selectTemplate(template: TableViewTemplate): void {
  selectedId.value = template.id;
  draftName.value = template.name;
  draftColumns.value = template.columns.map((column) => ({ ...column }));
  draftActions.jbrowse = template.actions.jbrowse;
  draftActions.genome_preview = template.actions.genome_preview;
  errorMessage.value = "";
}

function startNew(): void {
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
  errorMessage.value = "";
}

function addColumn(key: string): void {
  const candidate = candidates.value.find((item) => item.key === key);
  if (!candidate) return;
  draftColumns.value.push({
    key: candidate.key,
    label_zh: candidate.label,
    label_en: candidate.label,
    visible: true,
  });
}

function move(index: number, delta: number): void {
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
