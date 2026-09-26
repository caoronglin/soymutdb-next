<template>
  <ConfigProvider :theme="themeConfig" component-size="middle">
    <div class="flex min-h-screen flex-col bg-background text-foreground">
      <!-- Header bar — wraps into two rows on narrow screens so the back
           button, locus input and track actions stay usable. -->
      <AppHeader
        v-model:assembly-name="assemblyName"
        v-model:locus-input="locusInput"
        :is-embedded="isEmbedded"
        :parent-origin="parentOrigin"
        :current-locus="currentLocus"
        :active-tracks="activeTracks"
        :is-fullscreen="isFullscreen"
        :share-copied="shareCopied"
        @navigate="handleNavigate"
        @share="handleShare"
        @toggle-fullscreen="toggleFullscreen"
      />

      <!-- Genome view container -->
      <main
        ref="containerRef"
        class="jbrowse-container relative flex-1 overflow-hidden bg-background"
        :class="isFullscreen ? 'fixed inset-0 z-50' : ''"
        @wheel.prevent="handleWheel"
        @pointerdown="startPan"
        @pointermove="movePan"
        @pointerup="endPan"
        @pointercancel="endPan"
      >
        <LoadingPlaceholder v-if="isLoading" />
        <ErrorPlaceholder v-else-if="initError" :message="initError" @retry="reload" />
        <div v-else class="jbrowse-fade-in h-full w-full">
          <GenomeBrowser
            :assembly-key="browserModel.assemblyKey"
            :ref-name="viewport.refName"
            :tracks="browserModel.tracks"
            :region="viewport"
            :width-px="widthPx"
            :provider="provider"
            :assemblies="browserModel.assemblies"
          />
        </div>
      </main>

      <!-- Footer -->
      <AppFooter :active-count="activeTracks.length" />
    </div>
  </ConfigProvider>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, useTemplateRef, watch } from "vue";
import { http } from "@soymutdb/api-client";
import {
  TextSearchReader,
  UriFileProvider,
  uriLocation,
  type AssemblyContext,
  type TrackConfig,
} from "@soymutdb/genome-data";
import { GenomeBrowser, useGenomeViewport } from "@soymutdb/genome-view";
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import AppFooter from "./components/AppFooter.vue";
import AppHeader from "./components/AppHeader.vue";
import ErrorPlaceholder from "./components/ErrorPlaceholder.vue";
import LoadingPlaceholder from "./components/LoadingPlaceholder.vue";
import {
  ALL_TRACKS,
  DEFAULT_ASSEMBLY,
  DEFAULT_TRACKS,
  buildAssembly,
  buildJBrowseConfig,
  type JBrowseAssembly,
  type JBrowseConfig,
  type JBrowseTrack,
  type TrixSearchAdapter,
} from "./config";
import {
  buildDeepLink,
  formatLocus,
  parseDeepLink,
  parseLocus,
  toOneBased,
  toZeroBased,
  type DeepLinkParams,
} from "./deep-link";
import { parsePortalMessage, postToParent, type InitPayload } from "./bridge";

/** JBrowse config payload returned by the API. */
interface JBrowseConfigResponse {
  assembly: JBrowseAssembly;
  tracks: JBrowseTrack[];
}

/** Everything GenomeBrowser needs for the current assembly. */
interface BrowserModel {
  assemblyKey: string;
  assemblies: AssemblyContext[];
  tracks: TrackConfig[];
}

const DEFAULT_REGION = { refName: "chr01", start: 0, end: 1_000_000 } as const;

// Parse initial deep-link params from the URL.
const initialParams: DeepLinkParams =
  typeof window === "undefined" ? {} : parseDeepLink(window.location.search);

// Embedded mode: the portal appends ?portalOrigin=<origin> when loading us in
// an iframe. Without it we stay fully standalone.
const isEmbedded = Boolean(initialParams.portalOrigin);
const parentOrigin =
  initialParams.portalOrigin ?? (typeof window === "undefined" ? "*" : window.location.origin);

const initialLocus = initialParams.locus;
const initialRef = initialLocus ? parseLocus(initialLocus) : null;
const initialWindow = initialRef ? toZeroBased(initialRef.start, initialRef.end) : null;

const viewport = useGenomeViewport({
  assemblyKey: initialParams.assembly ?? DEFAULT_ASSEMBLY.name,
  refName: initialRef?.refName ?? DEFAULT_REGION.refName,
  start: initialWindow?.[0] ?? DEFAULT_REGION.start,
  end: initialWindow?.[1] ?? DEFAULT_REGION.end,
});

const assemblyName = ref(initialParams.assembly ?? DEFAULT_ASSEMBLY.name);
const activeTracks = ref<string[]>(initialParams.tracks ?? DEFAULT_TRACKS);
const currentLocus = ref<string | undefined>(initialLocus);
const release = ref<string | undefined>(initialParams.release);
const locusInput = ref(initialLocus ?? "");
const isFullscreen = ref(false);
const shareCopied = ref(false);
const isLoading = ref(true);
const initError = ref<string | null>(null);
const widthPx = ref(800);
const isDark = ref(
  typeof document !== "undefined" &&
    document.documentElement.getAttribute("data-theme") === "dark",
);
const themeConfig = computed(() => createThemeConfig({ dark: isDark.value }));

const containerRef = useTemplateRef<HTMLElement>("containerRef");
const provider = new UriFileProvider();

// Fetch the backend track config; fall back to the built-in defaults when the
// API is unavailable so the browser still works.
const rawConfig = ref<JBrowseConfigResponse | null>(null);
const config = computed<JBrowseConfig>(() =>
  buildJBrowseConfig(
    rawConfig.value?.assembly ?? buildAssembly(assemblyName.value),
    rawConfig.value?.tracks ?? ALL_TRACKS,
  ),
);

const browserModel = shallowRef<BrowserModel>({
  assemblyKey: "",
  assemblies: [],
  tracks: [],
});

function toAssemblies(assembly: JBrowseAssembly, refName: string): AssemblyContext[] {
  return [
    {
      key: assembly.name,
      name: assembly.name,
      aliases: assembly.aliases,
      // The host declares the reference it is querying; genome-data resolves
      // every read inside exactly this assembly.
      refNames: refName ? [refName] : [],
    },
  ];
}

function toTrackConfig(track: JBrowseTrack): TrackConfig {
  return {
    trackId: track.trackId,
    name: track.name,
    type: track.type,
    assemblyNames: track.assemblyNames,
    category: track.category,
    description: track.description,
    adapter: track.adapter,
    renderer: track.renderer,
    displays: track.displays,
    metadata: track.metadata,
  };
}

function selectTracks(
  tracks: JBrowseTrack[],
  activeIds: string[],
  assembly: JBrowseAssembly,
): TrackConfig[] {
  const selected: TrackConfig[] = [];
  const seen = new Set<string>();
  for (const id of activeIds) {
    const actualId = id === "reference_sequence" ? assembly.sequence.trackId : id;
    if (seen.has(actualId)) continue;
    const track = tracks.find((candidate) => candidate.trackId === actualId);
    if (!track) continue;
    seen.add(actualId);
    selected.push(toTrackConfig(track));
  }
  return selected;
}

async function loadConfig(): Promise<void> {
  try {
    rawConfig.value = await http.get<JBrowseConfigResponse>("/tracks/jbrowse-config", {
      params: { assembly: assemblyName.value },
    });
  } catch {
    rawConfig.value = null;
  }
}

// Rebuild the browser model whenever the config, visible tracks or reference
// change. Unknown track types are skipped by GenomeBrowser itself.
watch(
  [config, activeTracks, () => viewport.refName],
  () => {
    try {
      const assembly = config.value.assemblies[0] ?? DEFAULT_ASSEMBLY;
      browserModel.value = {
        assemblyKey: assembly.name,
        assemblies: toAssemblies(assembly, viewport.refName),
        tracks: selectTracks(config.value.tracks, activeTracks.value, assembly),
      };
      initError.value = null;
    } catch (error) {
      initError.value =
        error instanceof Error ? error.message : "Failed to initialise genome browser";
    }
  },
  { immediate: true },
);

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

function syncLocusFromViewport(): void {
  const [start, end] = toOneBased(viewport.start, viewport.end);
  currentLocus.value = formatLocus({ refName: viewport.refName, start, end });
}

function applyLocus(locus: string): void {
  const parsed = parseLocus(locus);
  if (!parsed) {
    void navToSearchResults(locus);
    return;
  }
  const [start, end] = toZeroBased(parsed.start, parsed.end);
  viewport.gotoLocus(parsed.refName, start, end);
}

/**
 * Resolve a gene/feature search through the Trix index. The payload keeps the
 * location as an opaque string, so decode the first location-like token.
 */
async function navToSearchResults(input: string): Promise<void> {
  const adapter: TrixSearchAdapter | undefined = config.value.aggregateTextSearchAdapters?.[0];
  if (!adapter) {
    console.warn(`[JBrowse] No text-search index configured for "${input}"`);
    return;
  }
  try {
    const reader = new TextSearchReader({
      provider,
      ix: uriLocation(adapter.ixFilePath.uri),
      ixx: uriLocation(adapter.ixxFilePath.uri),
      trackId: adapter.textSearchAdapterId,
    });
    const [hit] = await reader.search(input, 1);
    const target = hit ? decodeTrixLocation(hit.label) : null;
    if (target) applyLocus(target);
  } catch (error) {
    console.warn(`[JBrowse] Text search failed for "${input}"`, error);
  }
}

function decodeTrixLocation(label: string): string | null {
  const normalized = label.replace(/\|/g, ",");
  const match = normalized.match(/([A-Za-z0-9_.]+):([\d,]+)(?:\.\.|-)([\d,]+)/);
  if (!match) return null;
  const start = Number.parseInt(match[2].replace(/,/g, ""), 10);
  const end = Number.parseInt(match[3].replace(/,/g, ""), 10);
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return `${match[1]}:${start}-${end}`;
}

function handleNavigate(): void {
  const trimmed = locusInput.value.trim();
  if (!trimmed) return;
  const parsed = parseLocus(trimmed);
  if (!parsed) {
    void navToSearchResults(trimmed);
    return;
  }
  const [start, end] = toZeroBased(parsed.start, parsed.end);
  viewport.gotoLocus(parsed.refName, start, end);
  currentLocus.value = formatLocus(parsed);
}

// ---------------------------------------------------------------------------
// Viewport interaction (wheel zoom + drag pan)
// ---------------------------------------------------------------------------

let panPointerId: number | null = null;
let panStartX = 0;
let panStartBp = 0;

function handleWheel(event: WheelEvent): void {
  const element = containerRef.value;
  if (!element) return;
  const rect = element.getBoundingClientRect();
  const fraction = Math.min(1, Math.max(0, (event.clientX - rect.left) / (rect.width || 1)));
  const anchor = viewport.start + (viewport.end - viewport.start) * fraction;
  viewport.zoom(event.deltaY > 0 ? 1.2 : 1 / 1.2, anchor);
  syncLocusFromViewport();
}

function startPan(event: PointerEvent): void {
  if (event.button !== 0 || !containerRef.value) return;
  panPointerId = event.pointerId;
  panStartX = event.clientX;
  panStartBp = viewport.start;
  containerRef.value.setPointerCapture(event.pointerId);
}

function movePan(event: PointerEvent): void {
  if (panPointerId !== event.pointerId) return;
  const bpPerPx = (viewport.end - viewport.start) / (containerRef.value?.clientWidth || widthPx.value || 1);
  const delta = (panStartX - event.clientX) * bpPerPx;
  viewport.pan(Math.round(panStartBp + delta - viewport.start));
  syncLocusFromViewport();
}

function endPan(event: PointerEvent): void {
  if (panPointerId !== event.pointerId) return;
  containerRef.value?.releasePointerCapture(event.pointerId);
  panPointerId = null;
}

// ---------------------------------------------------------------------------
// postMessage bridge with the embedding portal
// ---------------------------------------------------------------------------

// Apply an `init` message: assembly/tracks changes rebuild the view, locus-only
// changes navigate in place.
function applyInit(payload: InitPayload | undefined): void {
  if (!payload || typeof payload !== "object") return;

  const tracks = Array.isArray(payload.tracks)
    ? payload.tracks.filter((value): value is string => typeof value === "string" && value.length > 0)
    : undefined;
  const assembly =
    typeof payload.assembly === "string" && payload.assembly.length > 0 ? payload.assembly : undefined;
  const locus =
    typeof payload.locus === "string" && payload.locus.length > 0 ? payload.locus : undefined;

  if (typeof payload.release === "string" && payload.release) release.value = payload.release;

  // Filter track ids against what the current config actually provides.
  const knownTrackIds = new Set<string>();
  for (const track of config.value.tracks) knownTrackIds.add(track.trackId);
  const refTrackId = config.value.assemblies[0]?.sequence.trackId;
  if (refTrackId) knownTrackIds.add(refTrackId);
  const usableTracks = tracks?.filter((id) => knownTrackIds.has(id));

  const sameAssembly = !assembly || assembly === assemblyName.value;
  const sameTracks =
    !usableTracks ||
    usableTracks.length === 0 ||
    (usableTracks.length === activeTracks.value.length &&
      [...usableTracks].sort().join(",") === [...activeTracks.value].sort().join(","));

  if (sameAssembly && sameTracks) {
    if (locus && locus !== currentLocus.value) {
      applyLocus(locus);
      currentLocus.value = locus;
      locusInput.value = locus;
    }
    return;
  }

  if (assembly) assemblyName.value = assembly;
  if (usableTracks && usableTracks.length > 0) activeTracks.value = usableTracks;
  if (locus) {
    applyLocus(locus);
    currentLocus.value = locus;
    locusInput.value = locus;
  }
}

function handleMessage(event: MessageEvent): void {
  const message = parsePortalMessage(event, parentOrigin);
  if (!message) return; // already warned inside the validator
  if (message.type === "init") {
    applyInit(message.payload as InitPayload | undefined);
  } else if (message.type === "selection-change") {
    // Reserved by the bridge contract; nothing to apply yet.
  } else {
    console.warn(`[JBrowse] Ignoring unexpected bridge message type: ${String(message.type)}`);
  }
}

// Announce readiness (or failure) to the portal.
let readySentFor = "";

function postReady(): void {
  if (!isEmbedded || initError.value) return;
  const assemblyKey = browserModel.value.assemblyKey;
  if (!assemblyKey || readySentFor === assemblyKey) return;
  readySentFor = assemblyKey;
  postToParent(
    { type: "ready", payload: { assembly: assemblyName.value, locus: currentLocus.value } },
    parentOrigin,
  );
}

watch(initError, (message) => {
  if (isEmbedded && message) {
    postToParent({ type: "error", payload: { message } }, parentOrigin);
  }
});

watch(
  () => browserModel.value.assemblyKey,
  () => {
    readySentFor = "";
    postReady();
  },
);

// Notify the portal about viewport changes (debounced 300ms).
let locusTimer: number | null = null;
watch(currentLocus, () => {
  if (!isEmbedded || !currentLocus.value || !browserModel.value.assemblyKey) return;
  if (locusTimer !== null) window.clearTimeout(locusTimer);
  locusTimer = window.setTimeout(() => {
    postToParent(
      {
        type: "locus-change",
        payload: {
          assembly: assemblyName.value,
          locus: currentLocus.value,
          tracks: activeTracks.value,
        },
      },
      parentOrigin,
    );
  }, 300);
});

// Keep the URL in sync (replaceState to avoid history spam). portalOrigin is
// intentionally never emitted, matching the deep-link contract.
watch([currentLocus, activeTracks, assemblyName, release], () => {
  if (typeof window === "undefined") return;
  window.history.replaceState(
    null,
    "",
    buildDeepLink({
      locus: currentLocus.value,
      tracks: activeTracks.value,
      assembly: assemblyName.value,
      release: release.value,
    }),
  );
});

watch(assemblyName, () => {
  rawConfig.value = null;
  void loadConfig();
});

// ---------------------------------------------------------------------------
// Shell actions
// ---------------------------------------------------------------------------

function toggleFullscreen(): void {
  const element = containerRef.value;
  if (!element) return;
  void (async () => {
    try {
      if (!document.fullscreenElement) {
        await element.requestFullscreen();
        isFullscreen.value = true;
      } else {
        await document.exitFullscreen();
        isFullscreen.value = false;
      }
    } catch {
      // Fullscreen may be blocked; fail silently.
    }
  })();
}

function handleFullscreenChange(): void {
  isFullscreen.value = Boolean(document.fullscreenElement);
}

async function handleShare(): Promise<void> {
  const url = buildDeepLink({
    locus: currentLocus.value,
    tracks: activeTracks.value,
    assembly: assemblyName.value,
    release: release.value,
  });
  try {
    await navigator.clipboard.writeText(url);
    shareCopied.value = true;
    window.setTimeout(() => {
      shareCopied.value = false;
    }, 2000);
  } catch {
    // Fallback: let the user copy the URL manually.
    window.prompt("Copy this link to share:", url);
  }
}

function reload(): void {
  window.location.reload();
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

let widthObserver: ResizeObserver | null = null;
let themeObserver: MutationObserver | null = null;

onMounted(() => {
  isLoading.value = false;
  if (isEmbedded) window.addEventListener("message", handleMessage);
  document.addEventListener("fullscreenchange", handleFullscreenChange);

  const element = containerRef.value;
  if (element) {
    widthPx.value = element.clientWidth || widthPx.value;
    if (typeof ResizeObserver !== "undefined") {
      widthObserver = new ResizeObserver(() => {
        widthPx.value = element.clientWidth || widthPx.value;
      });
      widthObserver.observe(element);
    }
  }

  themeObserver = new MutationObserver(() => {
    isDark.value = document.documentElement.getAttribute("data-theme") === "dark";
  });
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });

  void loadConfig();
  postReady();
});

onBeforeUnmount(() => {
  window.removeEventListener("message", handleMessage);
  document.removeEventListener("fullscreenchange", handleFullscreenChange);
  widthObserver?.disconnect();
  themeObserver?.disconnect();
  if (locusTimer !== null) window.clearTimeout(locusTimer);
});
</script>
