<script setup lang="ts" generic="T">
import AppIcon from "./AppIcon.vue";
import type { TableColumn, TableSort } from "./table-types";

/**
 * Presentational data table for the portal list/detail surfaces.
 *
 * Ported from the React baseline `components/data-table.tsx`: sticky muted
 * header, hover row highlight, right-aligned tabular numerics, sort buttons
 * with `aria-sort`, skeleton loading rows, an inline empty state, and an
 * optional compact card list below `md` so a wide table never forces the page
 * to scroll sideways on a phone.
 *
 * Purely presentational: it owns no fetching and no URL state. Cells are
 * overridden per column through the dynamic `#cell-<column id>` slot, so views
 * keep their own formatting (links, badges, fallbacks) exactly as before.
 */
const props = withDefaults(
  defineProps<{
    columns: TableColumn[];
    rows: readonly T[];
    /** Stable row key; falls back to the index when the caller has no id. */
    rowKey?: (row: T, index: number) => string;
    /** Extra row attributes, e.g. `data-testid` / `data-public-id`. */
    rowAttrs?: (row: T, index: number) => Record<string, string>;
    loading?: boolean;
    skeletonRows?: number;
    emptyTitle?: string;
    emptyDescription?: string;
    sort?: TableSort | null;
    /** Render the compact card list below the `md` breakpoint. */
    responsive?: boolean;
    ariaLabel?: string;
  }>(),
  {
    rowKey: undefined,
    rowAttrs: undefined,
    loading: false,
    skeletonRows: 6,
    emptyTitle: "No results found",
    emptyDescription: "",
    sort: null,
    responsive: false,
    ariaLabel: "",
  },
);

const emit = defineEmits<{ sort: [sortKey: string] }>();

const isRightAligned = (column: TableColumn) => column.numeric || column.align === "right";
const sortedDir = (column: TableColumn) =>
  column.sortKey && props.sort?.key === column.sortKey ? props.sort.dir : undefined;
/** The column that heads the mobile card — the first one when unmarked. */
const primaryColumn = (): TableColumn | undefined =>
  props.columns.find((column) => column.primary) ?? props.columns[0];
</script>

<template>
  <div class="flex flex-col gap-4">
    <div
      class="overflow-x-auto rounded-xl border bg-card shadow-sm"
      :class="responsive && !loading && rows.length > 0 ? 'hidden md:block' : ''"
    >
      <table class="w-full border-collapse text-sm" :aria-label="ariaLabel || undefined">
        <thead class="sticky top-0 z-10 bg-muted/60 backdrop-blur">
          <tr class="border-b border-border">
            <th
              v-for="(column, index) in columns"
              :key="column.id ?? index"
              scope="col"
              :data-testid="column.headerTestId"
              class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground"
              :class="[
                isRightAligned(column) && 'text-right',
                column.align === 'center' && 'text-center',
                column.headerClass,
              ]"
              :style="column.width ? { width: column.width } : undefined"
              :aria-sort="
                sortedDir(column)
                  ? sortedDir(column) === 'asc'
                    ? 'ascending'
                    : 'descending'
                  : undefined
              "
            >
              <button
                v-if="column.sortKey"
                type="button"
                :data-testid="column.sortTestId"
                class="inline-flex items-center gap-1 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                :class="[isRightAligned(column) && 'flex-row-reverse', sortedDir(column) && 'text-foreground']"
                @click="emit('sort', column.sortKey)"
              >
                <span>{{ column.header }}</span>
                <AppIcon
                  v-if="sortedDir(column)"
                  :name="sortedDir(column) === 'asc' ? 'arrow-up' : 'arrow-down'"
                  class="size-3.5"
                />
                <AppIcon v-else name="sort" class="size-3.5 opacity-40" />
              </button>
              <template v-else>{{ column.header }}</template>
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-if="loading">
            <tr
              v-for="row in skeletonRows"
              :key="`skeleton-${row}`"
              class="border-b border-border last:border-0"
            >
              <td
                v-for="column in columns"
                :key="column.id"
                class="px-4 py-3"
                :class="[isRightAligned(column) && 'text-right', column.align === 'center' && 'text-center']"
              >
                <div class="h-4 w-full max-w-[120px] animate-pulse rounded bg-muted" />
              </td>
            </tr>
          </template>
          <tr v-else-if="rows.length === 0">
            <td :colspan="columns.length" class="px-4 py-12">
              <div class="flex flex-col items-center gap-3 text-center">
                <div class="flex size-10 items-center justify-center rounded-full bg-muted">
                  <AppIcon name="inbox" class="size-5 text-muted-foreground" />
                </div>
                <p class="font-medium">{{ emptyTitle }}</p>
                <p v-if="emptyDescription" class="max-w-sm text-sm text-muted-foreground">
                  {{ emptyDescription }}
                </p>
              </div>
            </td>
          </tr>
          <template v-else>
            <tr
              v-for="(row, rowIndex) in rows"
              :key="rowKey ? rowKey(row, rowIndex) : rowIndex"
              v-bind="rowAttrs ? rowAttrs(row, rowIndex) : undefined"
              class="border-b border-border transition-colors last:border-0 hover:bg-muted/50"
            >
              <td
                v-for="column in columns"
                :key="column.id"
                class="px-4 py-3 align-middle"
                :class="[
                  isRightAligned(column) && 'text-right font-mono tabular-nums',
                  column.align === 'center' && 'text-center',
                  column.cellClass,
                ]"
              >
                <slot :name="`cell-${column.id}`" :row="row" :index="rowIndex">
                  {{ (row as Record<string, unknown>)[column.id] ?? "—" }}
                </slot>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <ul
      v-if="responsive && !loading && rows.length > 0"
      class="grid gap-3 md:hidden"
      :aria-label="ariaLabel ? `${ariaLabel} (compact)` : undefined"
    >
      <li v-for="(row, rowIndex) in rows" :key="rowKey ? rowKey(row, rowIndex) : rowIndex">
        <div
          class="rounded-xl border bg-card p-4 shadow-sm"
          v-bind="rowAttrs ? rowAttrs(row, rowIndex) : undefined"
        >
          <div v-if="primaryColumn()" class="font-medium">
            <slot :name="`cell-${primaryColumn()!.id}`" :row="row" :index="rowIndex">
              {{ (row as Record<string, unknown>)[primaryColumn()!.id] ?? "—" }}
            </slot>
          </div>
          <dl class="mt-3 grid gap-2">
            <div
              v-for="column in columns.filter((item) => item !== primaryColumn())"
              :key="column.id"
              class="flex items-baseline justify-between gap-3"
            >
              <dt class="text-xs text-muted-foreground">{{ column.header }}</dt>
              <dd :class="['text-sm', isRightAligned(column) && 'font-mono tabular-nums']">
                <slot :name="`cell-${column.id}`" :row="row" :index="rowIndex">
                  {{ (row as Record<string, unknown>)[column.id] ?? "—" }}
                </slot>
              </dd>
            </div>
          </dl>
        </div>
      </li>
    </ul>

    <slot name="footer" />
  </div>
</template>
