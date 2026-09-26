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
        :search-status="searchNotice?.message"
        :search-tone="searchNotice?.tone"
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
import { http, searchGenes } from "@soymutdb/api-client";
import {
  AssemblyRefNameLoader,
  createTextSearchDataSource,
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
  sequenceFileLocations,
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
  type ParsedLocus,
} from "./deep-link";
import {
  parseTextSearchLabel,
  resolveLocusInput,
  type GeneSearchHit,
} from "./gene-search";
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

// Full reference-name lists come from the assembly FASTA index, loaded once per
// assembly. Until that resolves (or if it fails) the current viewport reference
// is the only declared name, so rendering never waits on this I/O.
const refNameLoaders = new Map<string, AssemblyRefNameLoader>();
const refNames = shallowRef<readonly string[] | null>(null);
let refNameRequest = 0;

function refNameLoaderFor(assembly: JBrowseAssembly): AssemblyRefNameLoader | null {
  const locations = sequenceFileLocations(assembly);
  if (!locations) return null;
  let loader = refNameLoaders.get(assembly.name);
  if (!loader) {
    loader = new AssemblyRefNameLoader({
      provider,
      assembly: { key: assembly.name, name: assembly.name, aliases: assembly.aliases },
      trackId: assembly.sequence.trackId,
      fasta: uriLocation(locations.fasta),
      fai: uriLocation(locations.fai),
      gzi: uriLocation(locations.gzi),
    });
    refNameLoaders.set(assembly.name, loader);
  }
  return loader;
}

async function ensureRefNames(): Promise<void> {
  const assembly = config.value.assemblies[0];
  if (!assembly) {
    refNames.value = null;
    return;
  }
  const loader = refNameLoaderFor(assembly);
  if (!loader) {
    refNames.value = null;
    return;
  }
  if (loader.cached) {
    refNames.value = loader.cached;
    return;
  }
  // Reset so a slow load for a newly selected assembly cannot keep the previous
  // assembly's names in scope.
  refNames.value = null;
  const request = ++refNameRequest;
  const fallback = viewport.refName ? [viewport.refName] : [];
  const names = await loader.load(fallback);
  if (request !== refNameRequest) return;
  if (config.value.assemblies[0]?.name !== assembly.name) return;
  refNames.value = names;
}

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

function toAssemblies(
  assembly: JBrowseAssembly,
  refNames: readonly string[],
): AssemblyContext[] {
  return [
    {
      key: assembly.name,
      name: assembly.name,
      aliases: assembly.aliases,
      // The full chromosome list comes from the FASTA index; the viewport
      // reference is only a fallback when that load fails, so every chromosome
      // resolves inside exactly this assembly.
      refNames: [...refNames],
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
  [config, activeTracks, () => viewport.refName, refNames],
  () => {
    try {
      const assembly = config.value.assemblies[0] ?? DEFAULT_ASSEMBLY;
      const names = refNames.value ?? (viewport.refName ? [viewport.refName] : []);
      browserModel.value = {
        assemblyKey: assembly.name,
        assemblies: toAssemblies(assembly, names),
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

// Load the chromosome list once per assembly; failures degrade to the current
// viewport reference rather than surfacing an error.
watch(
  config,
  () => {
    void ensureRefNames();
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

/** Search feedback shown under the locus box. */
const searchNotice = ref<{ tone: "info" | "error"; message: string } | null>(null);

/**
 * Resolve the locus box input: coordinate strings navigate locally, everything
 * else is treated as a gene identifier and resolved through lookupGene().
 */
async function applyLocus(input: string): Promise<void> {
  const trimmed = input.trim();
  if (!trimmed) return;
  const result = await resolveLocusInput(trimmed, { lookupGene });
  switch (result.kind) {
    case "coordinate":
      navigateToLocus(result.locus, { source: "coordinate" });
      return;
    case "gene":
      navigateToLocus(result.gene, {
        source: "gene",
        label: result.gene.geneId ? `Gene ${result.gene.geneId}` : "Gene",
      });
      return;
    case "not-found":
      searchNotice.value = {
        tone: "info",
        message: `No gene or location found for "${result.query}"`,
      };
      return;
    case "error":
      searchNotice.value = {
        tone: "error",
        message: `Search failed for "${result.query}": ${result.message}`,
      };
      return;
  }
}

function navigateToLocus(
  locus: ParsedLocus,
  options: { source: "coordinate" | "gene"; label?: string },
): void {
  const [start, end] = toZeroBased(locus.start, locus.end);
  viewport.gotoLocus(locus.refName, start, end);
  currentLocus.value = formatLocus(locus);
  searchNotice.value =
    options.source === "gene"
      ? { tone: "info", message: `${options.label ?? "Gene"} at ${formatLocus(locus)}` }
      : null;
}

/**
 * Resolve a gene identifier. The API is authoritative; a Trix index configured
 * for the current assembly is an offline fallback. The reader is built through
 * genome-data's data-source factory, so adapter selection is explicit and
 * assembly-scoped rather than an implicit "first adapter" default.
 */
async function lookupGene(query: string): Promise<GeneSearchHit | null> {
  let apiError: unknown;
  try {
    const response = await searchGenes({ q: query, page_size: 5 });
    const gene = response.items[0];
    if (gene) {
      return {
        gene_id: gene.gene_id,
        chromosome: gene.chromosome,
        start_pos: gene.start_pos,
        end_pos: gene.end_pos,
      };
    }
  } catch (error) {
    apiError = error;
  }

  const adapter = selectTextSearchAdapter(browserModel.value.assemblyKey);
  if (adapter) {
    try {
      const source = createTextSearchDataSource(adapter, {
        provider,
        assemblies: browserModel.value.assemblies,
      });
      const [hit] = await source.reader.search(query, 1);
      const decoded = hit ? parseTextSearchLabel(hit.label) : null;
      if (decoded) {
        return {
          chromosome: decoded.refName,
          start_pos: decoded.start,
          end_pos: decoded.end,
        };
      }
      return null;
    } catch (error) {
      if (apiError) throw apiError;
      console.warn(`[JBrowse] Text search failed for "${query}"`, error);
      return null;
    }
  }

  if (apiError) throw apiError;
  return null;
}

/** Pick the text-search adapter that explicitly names the current assembly. */
function selectTextSearchAdapter(assemblyName: string): TrixSearchAdapter | undefined {
  const adapters = config.value.aggregateTextSearchAdapters ?? [];
  return adapters.find((adapter) =>
    (adapter.assemblyNames.length > 0 ? adapter.assemblyNames : [assemblyName]).includes(
      assemblyName,
    ),
  );
}

function handleNavigate(): void {
  const trimmed = locusInput.value.trim();
  if (!trimmed) return;
  void applyLocus(trimmed);
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
      void applyLocus(locus);
      locusInput.value = locus;
    }
    return;
  }

  if (assembly) assemblyName.value = assembly;
  if (usableTracks && usableTracks.length > 0) activeTracks.value = usableTracks;
  if (locus) {
    void applyLocus(locus);
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
