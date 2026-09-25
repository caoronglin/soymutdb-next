<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
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
import { resolveJbrowseBaseUrl } from "../lib/deployment";
import { t } from "../lib/i18n";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Genome browser — JBrowse 2 embed with a postMessage bridge.
 *
 * Reliability model: the iframe counts as ready only when it posts a `ready`
 * bridge message. A timer can only flip "loading" into "timeout"; it can never
 * declare success. Every incoming message is validated against the canonical
 * JBrowse origin, the bridge source, and the version before it is trusted.
 */
const READY_TIMEOUT_MS = 15_000;

const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();

const jbrowseBaseUrl = computed(() =>
  resolveJbrowseBaseUrl(import.meta.env.VITE_JBROWSE_BASE_URL),
);
const jbrowseOrigin = computed(() => {
  try {
    return new URL(jbrowseBaseUrl.value).origin;
  } catch {
    return jbrowseBaseUrl.value;
  }
});

const params = computed(() => {
  const locus = typeof route.query.locus === "string" ? route.query.locus : typeof route.query.loc === "string" ? route.query.loc : "chr01";
  const rawTracks = route.query.tracks;
  const tracks = Array.isArray(rawTracks)
    ? rawTracks.map(String).filter(Boolean)
    : typeof rawTracks === "string"
      ? rawTracks.split(",").map((item) => item.trim()).filter(Boolean)
      : [];
  return {
    assembly: typeof route.query.assembly === "string" && route.query.assembly ? route.query.assembly : "Wm82.a4.v1",
    locus,
    tracks,
    release:
      typeof route.query.release === "string" && route.query.release
        ? route.query.release
        : site.releaseId ?? undefined,
  };
});

function buildJbrowseUrl(input: {
  assembly: string;
  locus: string;
  tracks: string[];
  release?: string;
  portalOrigin?: string;
}): string {
  const url = new URL(jbrowseBaseUrl.value);
  url.searchParams.set("assembly", input.assembly);
  url.searchParams.set("locus", input.locus);
  if (input.tracks.length > 0) url.searchParams.set("tracks", input.tracks.join(","));
  if (input.release) url.searchParams.set("release", input.release);
  if (input.portalOrigin) url.searchParams.set("portalOrigin", input.portalOrigin);
  return url.toString();
}

const portalOrigin = typeof window === "undefined" ? "" : window.location.origin;
const jbrowseSrc = computed(() => buildJbrowseUrl({ ...params.value, portalOrigin }));
const newTabSrc = computed(() => buildJbrowseUrl({ ...params.value }));

const iframeRef = ref<HTMLIFrameElement | null>(null);
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

function resetBridge() {
  status.value = "loading";
  errorMessage.value = null;
  initSent = false;
  window.clearTimeout(timeoutId);
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
    status.value = "ready";
    postInit();
    return;
  }
  if (message.type === "error") {
    const payload = message.payload as { message?: unknown } | undefined;
    errorMessage.value =
      typeof payload?.message === "string" && payload.message ? payload.message : t("browser.loadError");
    status.value = "error";
    return;
  }
  if (message.type === "locus-change") {
    const payload = message.payload as LocusChangePayload | undefined;
    if (!payload || typeof payload.locus !== "string" || !payload.locus) return;
    if (payload.locus !== params.value.locus) {
      void router.replace({
        path: "/browser",
        query: {
          assembly: payload.assembly || params.value.assembly,
          locus: payload.locus,
          tracks: payload.tracks?.join(",") || undefined,
          release: params.value.release,
        },
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
  window.clearTimeout(timeoutId);
});

watch(iframeKey, () => resetBridge());

function applyLocus() {
  const value = locusInput.value.trim();
  if (!value) return;
  void router.replace({ path: "/browser", query: { ...route.query, locus: value } });
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
            @change="router.replace({ path: '/browser', query: { ...$route.query, assembly: ($event.target as HTMLSelectElement).value } })"
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
        title="SoyMutDB genome browser (JBrowse 2)"
        class="mt-4 h-[70vh] w-full rounded-md border"
        data-testid="browser-iframe"
      />
    </div>
  </PortalLayout>
</template>
