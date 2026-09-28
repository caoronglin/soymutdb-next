<script setup lang="ts">
import { computed } from "vue";

import type { TableActions, TableColumn } from "@soymutdb/api-client";
import { formatNumber } from "@soymutdb/shared/format";
import { jbrowseUrl } from "@soymutdb/shared/genomics";
import { t } from "../lib/i18n";

/**
 * Template-driven table.
 *
 * The portal never hard-codes a column list: the API resolves an ordered set of
 * columns for the request's species, site variant and release, and this
 * component renders exactly what it is told — in that order. Two consequences an
 * operator depends on:
 *
 * * a column configured ``visible: false`` is staged but not rendered, so it can
 *   be prepared before it is published;
 * * the cross-assembly homolog columns are opt-in. A homolog column is keyed
 *   ``homolog:<species-or-version>``; it renders the matching entry from the
 *   row's homolog list and renders ``—`` when the row has none — never a zero
 *   or a blank that could be mistaken for an observation.
 *
 * The trailing actions (JBrowse / genome preview) are part of the same
 * template, so a deployment can turn a preview off without a code change.
 */
interface HomologEntry {
  species?: unknown;
  gene_id?: unknown;
  type?: unknown;
}

export interface ConfigurableRow {
  [key: string]: unknown;
}

const props = withDefaults(
  defineProps<{
    columns: readonly TableColumn[];
    actions?: TableActions;
    rows: readonly ConfigurableRow[];
    isLoading?: boolean;
    isError?: boolean;
    /** Assembly name used to build the JBrowse deep link for each row. */
    assemblyName?: string | null;
    caption?: string;
    routePrefix?: string;
  }>(),
  { actions: undefined, isLoading: false, isError: false, assemblyName: null, caption: undefined, routePrefix: "/genes" },
);

const visibleColumns = computed(() => props.columns.filter((column) => column.visible));

/** Values are rendered, never trusted as markup: everything goes through text. */
function cellValue(row: ConfigurableRow, column: TableColumn): string {
  const key = column.key;

  // Cross-assembly homolog column: ``homolog:<species or version>``.
  if (key.startsWith("homolog:")) {
    const wanted = key.slice("homolog:".length).toLowerCase();
    const homologs = Array.isArray(row.homologs) ? (row.homologs as HomologEntry[]) : [];
    const match = homologs.find((entry) => String(entry.species ?? "").toLowerCase() === wanted);
    return match && typeof match.gene_id === "string" ? match.gene_id : "—";
  }

  if (key === "mutation_system") {
    // Derived contract: line + position, so the column exists even when the
    // payload does not carry a precomputed label.
    const line = row.mutant_line_name ?? row.mutant_line_public_id ?? row.public_id;
    const position = row.position;
    if (line && position != null) return `${String(line)}·${String(position)}`;
    return line ? String(line) : position != null ? String(position) : "—";
  }

  if (key === "position") {
    const start = row.start_pos;
    const end = row.end_pos;
    if (typeof start === "number" && typeof end === "number") {
      return `${formatNumber(start)}–${formatNumber(end)}`;
    }
  }

  const value = row[key];
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Y" : "N";
  if (typeof value === "number") return formatNumber(value);
  if (Array.isArray(value)) return value.length === 0 ? "—" : value.join(", ");
  return String(value);
}

function confidenceLabel(value: string): string {
  switch (value.toUpperCase()) {
    case "H":
      return "高";
    case "M":
      return "中";
    case "L":
      return "低";
    default:
      return value;
  }
}

function rowLocus(row: ConfigurableRow): { chromosome: string; start: number; end: number } | null {
  const chromosome = row.chromosome;
  const position = row.position;
  if (typeof chromosome !== "string" || typeof position !== "number") return null;
  const end = typeof row.end_position === "number" ? row.end_position : position;
  return { chromosome, start: position, end };
}

function geneIdOf(row: ConfigurableRow): string | null {
  const geneId = row.gene_id;
  return typeof geneId === "string" && geneId ? geneId : null;
}
</script>

<template>
  <div data-testid="configurable-table">
      <table class="w-full text-sm" :aria-label="caption ?? 'Results'">
        <thead class="text-left opacity-60">
          <tr>
            <th v-for="column in visibleColumns" :key="column.key" scope="col" class="py-2">
              {{ column.label_en }}
            </th>
            <th v-if="actions?.jbrowse" scope="col" class="py-2">JBrowse 2</th>
            <th v-if="actions?.genome_preview" scope="col" class="py-2">{{ t("genes.geneLabel") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in rows" :key="index" data-testid="configurable-row" class="border-t">
            <td
              v-for="column in visibleColumns"
              :key="column.key"
              class="py-2"
              :data-column="column.key"
            >
              <span v-if="column.key === 'confidence'">
                {{ confidenceLabel(cellValue(row, column)) }}
              </span>
              <RouterLink
                v-else-if="column.key === 'gene_id' && geneIdOf(row)"
                :to="`${routePrefix}/${geneIdOf(row)}?assembly=${encodeURIComponent(assemblyName ?? '')}`"
                class="font-mono underline"
              >
                {{ cellValue(row, column) }}
              </RouterLink>
              <span v-else :class="column.key === 'mutation_system' ? 'font-mono' : ''">
                {{ cellValue(row, column) }}
              </span>
            </td>
            <td v-if="actions?.jbrowse" class="py-2">
              <a
                v-if="rowLocus(row)"
                class="underline"
                :href="jbrowseUrl(rowLocus(row)!, assemblyName ?? undefined)"
                target="_blank"
                rel="noopener noreferrer"
                :data-testid="'jbrowse-link-' + index"
              >
                JBrowse 2
              </a>
              <span v-else class="opacity-60">—</span>
            </td>
            <td v-if="actions?.genome_preview" class="py-2">
              <RouterLink
                v-if="geneIdOf(row)"
                :to="`${routePrefix}/${geneIdOf(row)}?assembly=${encodeURIComponent(assemblyName ?? '')}`"
                class="underline"
                :data-testid="'genome-link-' + index"
              >
                {{ geneIdOf(row) }}
              </RouterLink>
              <span v-else class="opacity-60">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
</template>
