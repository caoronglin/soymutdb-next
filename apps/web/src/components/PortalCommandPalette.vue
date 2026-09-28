<template>
  <div
    v-if="open"
    class="search-modal-backdrop flex items-start justify-center px-4 pt-[12vh]"
    role="dialog"
    aria-modal="true"
    :aria-label="t('commandPalette.label', { defaultValue: 'Quick search' })"
    data-testid="portal-command-palette"
    @click="closePalette"
  >
    <div
      class="search-modal-panel w-full max-w-xl overflow-hidden rounded-2xl border border-border bg-popover shadow-2xl"
      @click.stop
    >
      <div class="flex items-center gap-3 border-b border-border px-4 py-3">
        <CommandPaletteIcon name="search" class="size-5 shrink-0 text-muted-foreground" />
        <input
          id="portal-command-palette-input"
          ref="inputRef"
          v-model.trim="query"
          type="search"
          role="combobox"
          aria-expanded="true"
          :aria-controls="listboxId"
          :aria-activedescendant="activeId"
          :placeholder="t('commandPalette.placeholder', { defaultValue: 'Search pages, genes, variants…' })"
          class="h-9 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground"
          :aria-label="t('commandPalette.inputLabel', { defaultValue: 'Search' })"
          data-testid="portal-command-palette-input"
          @input="activeIndex = 0"
          @keydown="onInputKeydown"
        />
        <kbd class="hidden rounded border border-border bg-muted/60 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground sm:inline">ESC</kbd>
        <button
          type="button"
          class="rounded-md p-1 text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          :aria-label="t('commandPalette.close', { defaultValue: 'Close' })"
          data-testid="portal-command-palette-close"
          @click="closePalette"
        >
          <CommandPaletteIcon name="close" class="size-4" />
        </button>
      </div>

      <div
        :id="listboxId"
        role="listbox"
        class="max-h-[50vh] overflow-y-auto p-2"
        :aria-label="t('commandPalette.results', { defaultValue: 'Results' })"
      >
        <button
          v-for="(item, index) in items"
          :id="item.id"
          :key="item.id"
          type="button"
          role="option"
          :aria-selected="index === activeIndex"
          class="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors"
          :class="index === activeIndex ? 'bg-accent text-accent-foreground' : 'text-foreground hover:bg-accent/50'"
          :data-testid="`portal-command-palette-option-${item.to === '/search' ? 'search' : item.id.replace(`${uid}-`, '')}`"
          @click="runItem(item)"
          @mousemove="activeIndex = index"
        >
          <CommandPaletteIcon :name="item.icon" class="size-4 shrink-0 text-muted-foreground" />
          <span class="flex-1">
            <span class="font-medium">{{ item.label }}</span>
            <span v-if="item.description" class="ml-2 text-xs text-muted-foreground">{{ item.description }}</span>
          </span>
          <CommandPaletteIcon name="arrow-right" class="size-3.5 text-muted-foreground" />
        </button>

        <p
          v-if="hasQuery && matchingActions.length === 0"
          class="px-3 py-6 text-center text-sm text-muted-foreground"
          data-testid="portal-command-palette-empty"
        >
          {{ t("commandPalette.empty", { query: query.trim(), defaultValue: `No results for “${query.trim()}”` }) }}
        </p>
      </div>

      <div class="flex items-center justify-between border-t border-border px-4 py-2 text-xs text-muted-foreground">
        <div class="flex items-center gap-3">
          <span class="flex items-center gap-1">
            <kbd class="rounded border border-border bg-muted/60 px-1">↑</kbd>
            <kbd class="rounded border border-border bg-muted/60 px-1">↓</kbd>
            {{ t("commandPalette.hintNavigate", { defaultValue: "navigate" }) }}
          </span>
          <span class="flex items-center gap-1">
            <kbd class="rounded border border-border bg-muted/60 px-1">↵</kbd>
            {{ t("commandPalette.hintSelect", { defaultValue: "select" }) }}
          </span>
        </div>
        <span class="flex items-center gap-1">
          <kbd class="rounded border border-border bg-muted/60 px-1">⌘K</kbd>
          {{ t("commandPalette.hintOpen", { defaultValue: "to open" }) }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * PortalCommandPalette — ⌘K / Ctrl+K quick search overlay (Vue port).
 *
 * Ports the React `command-palette.tsx` (d3904c2105f34e5d74f3ae3a163d6b25f075bf64)
 * to the Vue portal: Cmd/Ctrl+K toggles, Escape closes, arrow keys move the
 * highlight and Enter runs the highlighted entry. The React baseline used
 * TanStack Router's `navigate`; here the router is `vue-router`. Everything else
 * (quick actions, search-submission entry, a11y contract, footer hints) mirrors
 * the baseline, plus the `isJbrowseEnabled()` gate the Vue header already uses
 * so a core-only deployment hides the `/browser` entry.
 */
import { computed, defineComponent, h, nextTick, onMounted, onUnmounted, ref, useId, useTemplateRef, watch } from "vue";
import { useRouter } from "vue-router";

import { isJbrowseEnabled } from "../lib/deployment";
import { t } from "../lib/i18n";
import { useSiteContextStore } from "../stores/site-context";

type IconName = "browser" | "gene" | "variant" | "blast" | "download" | "help" | "search" | "close" | "arrow-right";

/**
 * Icon set for the palette, inlined as SVG markup so no icon dependency is
 * added (the React baseline used @ant-design/icons).
 */
const ICONS: Record<IconName, string> = {
  browser: '<path d="m12 3 8 4.5-8 4.5-8-4.5z"/><path d="m4 12 8 4.5 8-4.5"/><path d="m4 16.6 8 4.4 8-4.4"/>',
  gene: '<path d="M7 3c0 4 10 4 10 9s-10 5-10 9"/><path d="M17 3c0 4-10 4-10 9s10 5 10 9"/><path d="M8.4 6.2h7.2M8.4 17.8h7.2M7 12h10"/>',
  variant:
    '<path d="M4 7h16M4 12h16M4 17h16"/><circle cx="9" cy="7" r="1.7"/><circle cx="15" cy="12" r="1.7"/><circle cx="7" cy="17" r="1.7"/>',
  blast: '<path d="M13.6 2.5 4.5 13.6H11l-.6 7.9 9.1-11.1H13z"/>',
  download: '<path d="M12 4v10"/><path d="m8 11 4 4 4-4"/><path d="M5 19.5h14"/>',
  help: '<path d="M4 5.6A2.6 2.6 0 0 1 6.6 3H19v15.4H6.6A2.6 2.6 0 0 0 4 21Z"/><path d="M4 18.4A2.6 2.6 0 0 1 6.6 16H19"/>',
  search: '<circle cx="11" cy="11" r="6.6"/><path d="m15.8 15.8 4.2 4.2"/>',
  "arrow-right": '<path d="M4.5 12h14"/><path d="m12.5 6 6 6-6 6"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
};

const CommandPaletteIcon = defineComponent({
  name: "CommandPaletteIcon",
  props: { name: { type: String as () => IconName, required: true } },
  setup: (props) => () =>
    h("svg", {
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": 1.7,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": "true",
      innerHTML: ICONS[props.name],
    }),
});

interface QuickAction {
  id: string;
  labelKey: string;
  label: string;
  descriptionKey: string;
  description: string;
  icon: IconName;
  to: string;
}

const QUICK_ACTIONS: readonly QuickAction[] = [
  {
    id: "browser",
    labelKey: "commandPalette.browser.label",
    label: "Open Genome Browser",
    descriptionKey: "commandPalette.browser.description",
    description: "Navigate to JBrowse viewer",
    icon: "browser",
    to: "/browser",
  },
  {
    id: "genes",
    labelKey: "commandPalette.genes.label",
    label: "Browse Genes",
    descriptionKey: "commandPalette.genes.description",
    description: "Search gene models",
    icon: "gene",
    to: "/genes",
  },
  {
    id: "variants",
    labelKey: "commandPalette.variants.label",
    label: "Search Variants",
    descriptionKey: "commandPalette.variants.description",
    description: "Query SNP/INDEL catalog",
    icon: "variant",
    to: "/variants",
  },
  {
    id: "blast",
    labelKey: "commandPalette.blast.label",
    label: "BLAST Search",
    descriptionKey: "commandPalette.blast.description",
    description: "Sequence similarity search",
    icon: "blast",
    to: "/blast",
  },
  {
    id: "downloads",
    labelKey: "commandPalette.downloads.label",
    label: "Download Data",
    descriptionKey: "commandPalette.downloads.description",
    description: "Bulk VCF/FASTA downloads",
    icon: "download",
    to: "/downloads",
  },
  {
    id: "help",
    labelKey: "commandPalette.help.label",
    label: "Help & Documentation",
    descriptionKey: "commandPalette.help.description",
    description: "User guides & tutorials",
    icon: "help",
    to: "/help",
  },
];

// A core-only deployment does not run JBrowse, so its entry is hidden rather
// than left as a link into a 502 — same gate as PortalHeader's nav.
const availableActions = computed<readonly QuickAction[]>(() =>
  QUICK_ACTIONS.filter((action) => action.to !== "/browser" || isJbrowseEnabled()),
);

/** One rendered row: either a quick action or the search-submission entry. */
interface PaletteItem {
  /** DOM id consumed by `aria-activedescendant`. */
  id: string;
  label: string;
  description?: string;
  icon: IconName;
  to: string;
}

const router = useRouter();
const site = useSiteContextStore();
const uid = useId();

const open = ref(false);
const query = ref("");
const activeIndex = ref(0);
const listboxId = `${uid}-listbox`;
const inputRef = useTemplateRef<HTMLInputElement>("inputRef");
/** Element focused before opening, so focus returns there on close. */
let opener: HTMLElement | null = null;

const hasQuery = computed(() => query.value.trim().length > 0);

/** Quick actions matching the current query (all of them while the query is empty). */
const matchingActions = computed<readonly QuickAction[]>(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return availableActions.value;
  return availableActions.value.filter(
    (action) =>
      action.label.toLowerCase().includes(q) || action.description.toLowerCase().includes(q),
  );
});

/**
 * Rows after filtering: the search-submission entry first (when the query is
 * non-empty), then the matching quick actions.
 */
const items = computed<readonly PaletteItem[]>(() => {
  const value = query.value.trim();
  const searchItem: PaletteItem[] = hasQuery.value
    ? [
        {
          id: `${uid}-search`,
          label: t("commandPalette.searchLabel", {
            query: value,
            defaultValue: `Search for “${value}”`,
          }),
          icon: "search",
          to: "/search",
        },
      ]
    : [];
  return [
    ...searchItem,
    ...matchingActions.value.map((action) => ({
      id: `${uid}-${action.id}`,
      label: t(action.labelKey, { defaultValue: action.label }),
      description: t(action.descriptionKey, { defaultValue: action.description }),
      icon: action.icon,
      to: action.to,
    })),
  ];
});

const activeId = computed(() => items.value[activeIndex.value]?.id);

function resetPalette() {
  query.value = "";
  activeIndex.value = 0;
}

function openPalette() {
  resetPalette();
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  open.value = true;
}

function closePalette() {
  resetPalette();
  open.value = false;
  void nextTick(() => {
    // Fall back to <body> when the opener is gone (e.g. the trigger unmounted).
    (opener?.isConnected ? opener : document.body).focus();
    opener = null;
  });
}

function togglePalette() {
  if (open.value) closePalette();
  else openPalette();
}

function runItem(item: PaletteItem) {
  // Captured before `closePalette()` resets the query the pushed URL is built from.
  const value = query.value.trim();
  closePalette();
  void router.push(
    item.to === "/search"
      ? {
          path: "/search",
          query: {
            q: value,
            ...(site.assemblyKey ? { assembly: site.assemblyKey } : {}),
          },
        }
      : { path: item.to },
  );
}

function onDocumentKeydown(event: KeyboardEvent) {
  const isToggleKey = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
  if (isToggleKey) {
    event.preventDefault();
    togglePalette();
    return;
  }
  if (!open.value) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closePalette();
  }
}

function onInputKeydown(event: KeyboardEvent) {
  if (event.key === "ArrowDown") {
    event.preventDefault();
    activeIndex.value = Math.min(activeIndex.value + 1, Math.max(0, items.value.length - 1));
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    activeIndex.value = Math.max(activeIndex.value - 1, 0);
  } else if (event.key === "Enter") {
    event.preventDefault();
    const item = items.value[activeIndex.value];
    if (item) runItem(item);
  }
}

// Opening focuses the input once the list is mounted.
watch(open, async (isOpen) => {
  if (!isOpen) return;
  await nextTick();
  inputRef.value?.focus();
});

onMounted(() => document.addEventListener("keydown", onDocumentKeydown));
onUnmounted(() => document.removeEventListener("keydown", onDocumentKeydown));
</script>
