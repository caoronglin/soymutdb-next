<template>
  <header
    class="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80"
  >
    <div class="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2">
      <a
        v-if="isEmbedded"
        :href="parentOrigin"
        target="_top"
        rel="noopener noreferrer"
        class="-ml-2 inline-flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-sm font-medium text-foreground/80 transition-colors hover:bg-accent hover:text-accent-foreground"
        :aria-label="t('browser.backToPortal')"
        :title="t('browser.backToPortal')"
      >
        <svg
          class="size-4"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="m12 19-7-7 7-7" />
          <path d="M19 12H5" />
        </svg>
        <span class="hidden md:inline">{{ t("browser.backToPortal") }}</span>
      </a>

      <div class="flex items-center gap-2">
        <span class="font-serif text-lg font-semibold text-primary">SoyMutDB</span>
        <span class="hidden text-sm text-muted-foreground sm:inline">Genome Browser</span>
      </div>

      <select
        v-model="assemblyName"
        class="h-8 w-36 shrink-0 rounded-md border border-input bg-background px-2 font-mono text-sm"
        aria-label="Select reference assembly"
      >
        <option value="Wm82v4.0">Wm82 v4.0</option>
        <option value="Wm82.a4.v1">Wm82.a4.v1</option>
        <option value="Wm82.a2.v1">Wm82.a2.v1</option>
      </select>

      <form
        class="flex min-w-0 flex-1 basis-full items-center gap-2 sm:ml-auto sm:basis-auto"
        @submit.prevent="emit('navigate')"
      >
        <div class="relative min-w-0 flex-1">
          <svg
            class="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            v-model="locusInput"
            type="text"
            placeholder="chr01:1-1000000 or gene ID"
            class="h-9 w-full min-w-0 rounded-md border border-input bg-background pl-8 font-mono text-sm"
            aria-label="Genomic location or gene search"
          />
        </div>
        <button
          type="submit"
          class="inline-flex h-7 shrink-0 items-center justify-center rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          Go
        </button>
      </form>

      <div class="ml-auto flex shrink-0 items-center gap-1 sm:ml-0">
        <button
          type="button"
          class="inline-flex size-9 items-center justify-center rounded-md text-foreground/80 transition-colors hover:bg-accent hover:text-accent-foreground"
          aria-label="Share current view"
          title="Share this view"
          @click="emit('share')"
        >
          <svg
            v-if="shareCopied"
            class="size-4 text-primary"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M20 6 9 17l-5-5" />
          </svg>
          <svg
            v-else
            class="size-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle cx="18" cy="5" r="3" />
            <circle cx="6" cy="12" r="3" />
            <circle cx="18" cy="19" r="3" />
            <line x1="8.59" x2="15.42" y1="13.51" y2="17.49" />
            <line x1="15.41" x2="8.59" y1="6.51" y2="10.49" />
          </svg>
        </button>
        <button
          type="button"
          class="inline-flex size-9 items-center justify-center rounded-md text-foreground/80 transition-colors hover:bg-accent hover:text-accent-foreground"
          :aria-label="isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'"
          :title="isFullscreen ? 'Exit fullscreen' : 'Fullscreen'"
          @click="emit('toggle-fullscreen')"
        >
          <svg
            v-if="isFullscreen"
            class="size-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="m14 10 7-7" />
            <path d="M20 10h-6V4" />
            <path d="m3 21 7-7" />
            <path d="M4 14h6v6" />
          </svg>
          <svg
            v-else
            class="size-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M15 3h6v6" />
            <path d="m21 3-7 7" />
            <path d="m3 21 7-7" />
            <path d="M9 21H3v-6" />
          </svg>
        </button>
      </div>
    </div>

    <p
      v-if="searchStatus"
      class="px-4 pb-1.5 text-xs"
      :class="searchTone === 'error' ? 'text-destructive' : 'text-muted-foreground'"
      role="status"
      aria-live="polite"
      data-testid="locus-search-status"
    >
      {{ searchStatus }}
    </p>

    <div
      class="flex items-center gap-3 border-t border-border bg-muted/30 px-4 py-1.5 text-xs text-muted-foreground"
    >
      <span class="font-mono">{{ currentLocus ?? "No location selected" }}</span>
      <span class="text-border">·</span>
      <span>{{ activeTracks.length }} active track{{ activeTracks.length === 1 ? "" : "s" }}</span>
      <span class="text-border">·</span>
      <span>Assembly: {{ assemblyName }}</span>
    </div>
  </header>
</template>

<script setup lang="ts">
import { t } from "../i18n";

const assemblyName = defineModel<string>("assemblyName", { required: true });
const locusInput = defineModel<string>("locusInput", { required: true });

defineProps<{
  isEmbedded: boolean;
  parentOrigin: string;
  currentLocus?: string;
  activeTracks: string[];
  isFullscreen: boolean;
  shareCopied: boolean;
  /** Feedback from the last locus/gene search (e.g. a "not found" message). */
  searchStatus?: string;
  searchTone?: "info" | "error";
}>();

const emit = defineEmits<{
  (event: "navigate"): void;
  (event: "share"): void;
  (event: "toggle-fullscreen"): void;
}>();
</script>
