<template>
  <div
    v-if="open"
    class="fixed inset-0 z-[70] flex items-start justify-center bg-black/45 px-4 pt-[12vh]"
    @mousedown="open = false"
  >
    <section
      class="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-popover shadow-2xl"
      role="dialog"
      aria-modal="true"
      :aria-label="t('admin.shell.commandPalette', { defaultValue: 'Commands' })"
      data-testid="admin-command-palette"
      @mousedown.stop
      @keydown="onKeyDown"
    >
      <div class="flex items-center gap-3 border-b border-border px-4">
        <svg aria-hidden="true" viewBox="0 0 24 24" class="size-4 shrink-0 text-muted-foreground" fill="none">
          <circle cx="11" cy="11" r="6" stroke="currentColor" stroke-width="1.7" />
          <path d="m15.5 15.5 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
        </svg>
        <input
          ref="input"
          v-model="query"
          type="text"
          role="combobox"
          class="h-14 min-w-0 flex-1 bg-transparent text-sm outline-none"
          :placeholder="t('admin.shell.commandPlaceholder', { defaultValue: 'Search commands or published genes…' })"
          :aria-expanded="true"
          aria-autocomplete="list"
          :aria-controls="listboxId"
          :aria-activedescendant="active ? `${listboxId}-${active.id}` : undefined"
          :aria-label="t('admin.shell.commandPlaceholder', { defaultValue: 'Search commands or published genes…' })"
          data-testid="admin-command-input"
          @input="activeIndex = 0"
        />
        <kbd class="rounded border border-border px-1.5 py-0.5 text-xs text-muted-foreground">Esc</kbd>
      </div>

      <ul :id="listboxId" class="max-h-80 overflow-y-auto p-2" role="listbox">
        <li v-for="(result, index) in results" :key="result.id">
          <button
            :id="`${listboxId}-${result.id}`"
            type="button"
            role="option"
            :aria-selected="index === activeIndex"
            class="flex w-full items-start rounded-lg px-3 py-2.5 text-left transition-colors"
            :class="index === activeIndex ? 'bg-accent text-accent-foreground' : 'hover:bg-accent/70'"
            @click="choose(result)"
            @mousemove="activeIndex = index"
          >
            <span class="min-w-0 flex-1">
              <span class="block text-sm font-medium">{{ result.label }}</span>
              <span class="mt-0.5 block truncate text-xs text-muted-foreground">{{ result.hint }}</span>
            </span>
            <span aria-hidden="true" class="ml-3 pt-1 text-xs text-muted-foreground">↵</span>
          </button>
        </li>
        <li
          v-if="results.length === 0 && !geneSearchFailed"
          class="px-3 py-8 text-center text-sm text-muted-foreground"
        >
          {{ t("admin.shell.commandEmpty", { defaultValue: "No matching command or gene." }) }}
        </li>
        <li v-if="geneSearchFailed" class="px-3 py-3 text-sm text-muted-foreground">
          {{ t("admin.shell.commandGeneUnavailable", { defaultValue: "Gene suggestions are unavailable; command search still works." }) }}
        </li>
      </ul>

      <div class="flex items-center justify-between border-t border-border px-4 py-2">
        <p class="text-xs text-muted-foreground">
          {{ t("admin.shell.commandHint", { defaultValue: "↑ ↓ to move, Enter to run. Gene suggestions start after 3 characters." }) }}
        </p>
        <p v-if="genesLoading" class="text-xs text-muted-foreground">{{ t("common.loading") }}</p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, useTemplateRef, watch } from "vue";

import { searchGenes, type GeneSummary } from "@soymutdb/api-client";

import { ADMIN_NAV_SECTIONS } from "../lib/admin-nav";
import { t } from "../lib/i18n";

/**
 * Command palette (⌘K / Ctrl+K) — the React console's route jump plus its
 * published-gene search. Restored because it was the fastest way into a route
 * and the Vue port had lost the shell shortcuts entirely.
 */
interface PaletteResult {
  id: string;
  label: string;
  hint: string;
  path?: string;
  geneId?: string;
}

const open = defineModel<boolean>({ required: true });
const emit = defineEmits<{ navigate: [path: string]; openGene: [geneId: string] }>();

const query = ref("");
const activeIndex = ref(0);
const genes = ref<GeneSummary[]>([]);
const geneSearchFailed = ref(false);
const genesLoading = ref(false);
const input = useTemplateRef<HTMLInputElement>("input");
const listboxId = "admin-command-listbox";
let geneTimer: ReturnType<typeof setTimeout> | undefined;

/** Recomputed on setup *and* on language change (`t` reads the language ref). */
const routeCommands = computed<PaletteResult[]>(() =>
  ADMIN_NAV_SECTIONS.flatMap((section) =>
    section.items.map((item) => ({
      id: `route-${item.path}`,
      label: t(item.labelKey, { defaultValue: item.labelDefault }),
      hint: `${t(section.labelKey, { defaultValue: section.labelDefault })} · ${item.path}`,
      path: item.path,
    })),
  ),
);

const results = computed<PaletteResult[]>(() => {
  const needle = query.value.trim().toLocaleLowerCase();
  const routes = needle
    ? routeCommands.value.filter((command) =>
        `${command.label} ${command.hint}`.toLocaleLowerCase().includes(needle),
      )
    : routeCommands.value;
  return [
    ...routes,
    ...genes.value.map((gene) => ({
      id: `gene-${gene.gene_id}`,
      label: gene.gene_id,
      hint: [gene.symbol, gene.name].filter(Boolean).join(" · ") || "gene",
      geneId: gene.gene_id,
    })),
  ];
});

const active = computed(() => results.value[activeIndex.value]);

watch(open, (isOpen) => {
  if (!isOpen) return;
  query.value = "";
  genes.value = [];
  geneSearchFailed.value = false;
  genesLoading.value = false;
  activeIndex.value = 0;
  requestAnimationFrame(() => input.value?.focus());
});

watch(query, (value) => {
  clearTimeout(geneTimer);
  const needle = value.trim();
  if (needle.length < 3) {
    genes.value = [];
    geneSearchFailed.value = false;
    genesLoading.value = false;
    return;
  }
  genesLoading.value = true;
  geneTimer = setTimeout(() => {
    const requested = needle;
    searchGenes({ q: requested, limit: 5 })
      .then((response) => {
        // A later keystroke may have already replaced the query.
        if (query.value.trim() !== requested) return;
        genes.value = response.items;
        geneSearchFailed.value = false;
      })
      .catch(() => {
        genes.value = [];
        geneSearchFailed.value = true;
      })
      .finally(() => {
        genesLoading.value = false;
      });
  }, 250);
});

watch(results, (value) => {
  if (activeIndex.value >= value.length) activeIndex.value = Math.max(value.length - 1, 0);
});

function choose(result: PaletteResult | undefined): void {
  if (!result) return;
  if (result.geneId) emit("openGene", result.geneId);
  else if (result.path) emit("navigate", result.path);
  open.value = false;
}

function onKeyDown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault();
    open.value = false;
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    activeIndex.value = Math.min(activeIndex.value + 1, Math.max(results.value.length - 1, 0));
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    activeIndex.value = Math.max(activeIndex.value - 1, 0);
  } else if (event.key === "Enter") {
    event.preventDefault();
    choose(active.value);
  }
}
</script>
