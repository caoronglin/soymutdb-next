<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  buildInitMessage,
  newSessionId,
  parseJbrowseMessage,
  type LocusChangePayload,
} from "@soymutdb/shared/jbrowse-bridge";
import { SOYBEAN_CHROMOSOMES } from "@soymutdb/shared/genomics";
import { Button } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { resolveJbrowseBaseUrl, resolveJbrowseOrigin } from "../lib/deployment";
import { t } from "../lib/i18n";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Genome browser — JBrowse 2 embed with a postMessage bridge.
 *
 * Reliability model: the iframe counts as ready only when it posts a `ready`
 * bridge message. A timer can only flip "loading" into "timeout"; it can never
 * declare success. Every incoming message is validated through the shared
 * jbrowse-bridge against the canonical JBrowse origin (derived from
 * VITE_JBROWSE_BASE_URL), the bridge source, the bridge version, the message
 * type and the iframe window before it is trusted.
 *
 * URL hygiene: only the documented deep-link keys (assembly, locus, tracks,
 * release) are written back to the address bar or forwarded into the frame URL,
 * so published or internal record identifiers cannot leak through this page's
 * URL or bridge logs.
 */
const READY_TIMEOUT_MS = 15_000;

const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();

// Captured once per render context. In the browser these are the live document
// values the bridge is validated against; during prerender there is no document
// and the relative base is kept relative so hydration can rewrite it.
const portalHref = typeof window === "undefined" ? "" : window.location.href;
const portalOrigin = typeof window === "undefined" ? "" : window.location.origin;

const jbrowseBaseUrl = computed(() =>
  resolveJbrowseBaseUrl(import.meta.env.VITE_JBROWSE_BASE_URL),
);
const jbrowseOrigin = computed(() =>
  resolveJbrowseOrigin(import.meta.env.VITE_JBROWSE_BASE_URL, portalOrigin),
);

const params = computed(() => {
  const locus =
    typeof route.query.locus === "string"
      ? route.query.locus
      : typeof route.query.loc === "string"
        ? route.query.loc
        : "chr01";
  const rawTracks = route.query.tracks;
  const tracks = Array.isArray(rawTracks)
    ? rawTracks.map(String).filter(Boolean)
    : typeof rawTracks === "string"
      ? rawTracks
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean)
      : [];
  return {
    assembly:
      typeof route.query.assembly === "string" && route.query.assembly
        ? route.query.assembly
        : "Wm82.a4.v1",
    locus,
    tracks,
    release:
      typeof route.query.release === "string" && route.query.release
        ? route.query.release
        : (site.releaseId ?? undefined),
  };
});

/**
 * Build a JBrowse URL. A relative base ("/jbrowse") is resolved against the
 * portal document; without one (prerender) the base is kept relative instead of
 * calling `new URL` with no base, which would throw.
 */
function buildJbrowseUrl(input: {
  assembly: string;
  locus: string;
  tracks: string[];
  release?: string;
  portalOrigin?: string;
}): string {
  const search = new URLSearchParams();
  search.set("assembly", input.assembly);
  search.set("locus", input.locus);
  if (input.tracks.length > 0) search.set("tracks", input.tracks.join(","));
  if (input.release) search.set("release", input.release);
  if (input.portalOrigin) search.set("portalOrigin", input.portalOrigin);
  const query = search.toString();
  if (portalHref) {
    const url = new URL(jbrowseBaseUrl.value, portalHref);
    url.search = query;
    return url.toString();
  }
  return query ? `${jbrowseBaseUrl.value}?${query}` : jbrowseBaseUrl.value;
}

const jbrowseSrc = computed(() => buildJbrowseUrl({ ...params.value, portalOrigin }));
const newTabSrc = computed(() => buildJbrowseUrl({ ...params.value }));

// Only the documented deep-link keys may persist. Unknown keys — including
// record identifiers — are dropped instead of being echoed back into the URL.
function singleQuery(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function listQuery(value: unknown): string | undefined {
  const raw = Array.isArray(value)
    ? value.map(String).join(",")
    : typeof value === "string"
      ? value
      : "";
  const joined = raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .join(",");
  return joined || undefined;
}

function replaceBrowserQuery(
  patch: Partial<Record<"assembly" | "locus" | "tracks" | "release", string | undefined>>,
): void {
  const query: Record<string, string> = {};
  const assembly = singleQuery(route.query.assembly);
  const locus = singleQuery(route.query.locus) ?? singleQuery(route.query.loc);
  const tracks = listQuery(route.query.tracks);
  const release = singleQuery(route.query.release);
  if (assembly) query.assembly = assembly;
  if (locus) query.locus = locus;
  if (tracks) query.tracks = tracks;
  if (release) query.release = release;
  for (const [key, value] of Object.entries(patch)) {
    if (value) query[key] = value;
    else delete query[key];
  }
  void router.replace({ path: "/browser", query });
}

const iframeRef = useTemplateRef<HTMLIFrameElement>("iframeRef");
const status = ref<"loading" | "ready" | "timeout" | "error">("loading");
const errorMessage = ref<string | null>(null);
const iframeKey = ref(0);
const sessionId = newSessionId();
const locusInput = ref(params.value.locus);
let initSent = false;
let timeoutId: number | undefined;

watch(
  params,
  (value) => {
    locusInput.value = value.locus;
  },
);

function clearReadyTimer() {
  window.clearTimeout(timeoutId);
  timeoutId = undefined;
}

function resetBridge() {
  status.value = "loading";
  errorMessage.value = null;
  initSent = false;
  clearReadyTimer();
  timeoutId = window.setTimeout(() => {
    // A late `ready` still recovers; the timer never claims success.
    if (status.value === "loading") status.value = "timeout";
  }, READY_TIMEOUT_MS);
}

function postInit() {
  const iframe = iframeRef.value;
  if (!iframe?.contentWindow) return;
  iframe.contentWindow.postMessage(
    buildInitMessage({
      assembly: params.value.assembly,
      locus: params.value.locus,
      tracks: params.value.tracks,
      release: params.value.release,
      sessionId,
    }),
    jbrowseOrigin.value,
  );
}

function handleMessage(event: MessageEvent) {
  const message = parseJbrowseMessage(
    event,
    jbrowseOrigin.value,
    iframeRef.value?.contentWindow ?? null,
  );
  if (!message) return;

  if (message.type === "ready") {
    if (initSent) return;
    initSent = true;
    clearReadyTimer();
    status.value = "ready";
    postInit();
    return;
  }
  if (message.type === "error") {
    const payload = message.payload as { message?: unknown } | undefined;
    clearReadyTimer();
    errorMessage.value =
      typeof payload?.message === "string" && payload.message ? payload.message : t("browser.loadError");
    status.value = "error";
    return;
  }
  if (message.type === "locus-change") {
    const payload = message.payload as LocusChangePayload | undefined;
    if (!payload || typeof payload.locus !== "string" || !payload.locus) return;
    if (payload.locus !== params.value.locus) {
      replaceBrowserQuery({
        assembly: payload.assembly || params.value.assembly,
        locus: payload.locus,
        tracks: listQuery(payload.tracks),
        release: params.value.release,
      });
    }
  }
}

onMounted(() => {
  window.addEventListener("message", handleMessage);
  resetBridge();
});

onBeforeUnmount(() => {
  window.removeEventListener("message", handleMessage);
  clearReadyTimer();
});

watch(iframeKey, () => resetBridge());

function applyLocus() {
  const value = locusInput.value.trim();
  if (!value) return;
  replaceBrowserQuery({ locus: value });
}

function selectAssembly(value: string) {
  replaceBrowserQuery({ assembly: value });
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-7xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("browser.title") }}</h1>
      <p class="mt-1 max-w-2xl text-sm opacity-70">
        {{ t("browser.subtitle") }} · {{ params.assembly }} · {{ params.locus }}
      </p>

      <form class="mt-4 flex flex-wrap items-end gap-3" role="search" @submit.prevent="applyLocus">
        <label class="text-sm opacity-70">
          {{ t("browser.locus") }}
          <input
            v-model="locusInput"
            class="mt-1 w-56 rounded-md border bg-background px-2 py-1.5 font-mono"
            data-testid="browser-locus-input"
          />
        </label>
        <label class="text-sm opacity-70">
          {{ t("browser.chromosome") }}
          <select
            class="mt-1 w-40 rounded-md border bg-background px-2 py-1.5"
            :value="params.assembly"
            data-testid="browser-assembly"
            @change="selectAssembly(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="name in SOYBEAN_CHROMOSOMES" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <Button html-type="submit" data-testid="browser-apply">{{ t("common.apply") }}</Button>
        <a
          class="underline"
          :href="newTabSrc"
          target="_blank"
          rel="noopener noreferrer"
          data-testid="browser-open-new-tab"
        >
          {{ t("browser.openNewTab") }}
        </a>
      </form>

      <p v-if="status === 'loading'" data-testid="browser-loading" class="mt-4 text-sm opacity-70" role="status">
        {{ t("browser.loading") }}
      </p>
      <div
        v-else-if="status === 'timeout'"
        class="mt-4 rounded-md border border-amber-500/50 p-4"
        data-testid="browser-timeout"
        role="alert"
      >
        <p class="text-sm">{{ t("browser.timeout") }}</p>
        <Button class="mt-2" data-testid="browser-retry" @click="iframeKey += 1">
          {{ t("common.retry") }}
        </Button>
      </div>
      <p v-else-if="status === 'error'" class="mt-4 text-sm text-red-700" data-testid="browser-error" role="alert">
        {{ errorMessage ?? t("browser.loadError") }}
      </p>
      <p v-else class="mt-4 text-sm opacity-70" data-testid="browser-ready">
        {{ t("browser.ready") }}
      </p>

      <iframe
        :key="iframeKey"
        ref="iframeRef"
        :src="jbrowseSrc"
        :title="t('browser.iframeTitle')"
        class="mt-4 h-[70vh] w-full rounded-md border"
        data-testid="browser-iframe"
      />
    </div>
  </PortalLayout>
</template>
