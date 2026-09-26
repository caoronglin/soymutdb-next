<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { getDownloadUrl, type DownloadFile } from "@soymutdb/api-client";
import { ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { downloadsQueryOptions } from "../lib/query-options";
import { t } from "../lib/i18n";

// Data downloads (Phase F). Lists downloadable artifacts via the neutral
// api-client, scoped by category. Downloads are fetched on demand through a
// short-lived presigned URL (never a leaked direct bucket link) with the
// catalogue URL as an explicit fallback, mirroring the React route. The cache
// key is scoped by category (this endpoint is not per release/assembly, so no
// release/assembly scoping is added here — DB-CORE-6 scoping applies to
// biological search, not the content catalogue).
const category = ref<string>("");
const downloadingId = ref<string | null>(null);

const query = useQuery(
  computed(() => downloadsQueryOptions({ category: category.value || undefined })),
);

const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const files = computed(() => toValue(query.data) ?? []);

async function download(file: DownloadFile) {
  downloadingId.value = file.id;
  try {
    const { url } = await getDownloadUrl(file.id);
    window.open(url, "_blank", "noopener,noreferrer");
  } catch {
    // A presign outage must not dead-end the page: fall back to the catalogue
    // URL like the React downloads route does.
    window.open(file.file_url, "_blank", "noopener,noreferrer");
  } finally {
    downloadingId.value = null;
  }
}

function formatSize(bytes: number | null): string {
  if (bytes === null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="mx-auto max-w-3xl p-8">
      <p class="text-sm opacity-70"><RouterLink to="/" class="underline">{{ t("nav.home") }}</RouterLink></p>
      <h1 class="mt-2 text-2xl font-semibold">{{ t("downloads.title") }}</h1>
      <p class="mt-2 text-sm opacity-70">{{ t("downloads.subtitle") }}</p>

      <div v-if="isLoading" data-testid="downloads-loading" class="mt-6 grid gap-3">
        <div v-for="index in 4" :key="index" class="h-16 w-full rounded bg-black/5" />
      </div>
      <div v-else-if="isError" data-testid="downloads-error" class="mt-6 rounded border border-red-300 p-5">
        <p class="font-medium">{{ t("downloads.loadError") }}</p>
      </div>

      <ul v-else data-testid="downloads-list" class="mt-6 grid gap-3">
        <li
          v-for="file in files"
          :key="file.id"
          data-testid="download-row"
          class="rounded-lg border p-4"
        >
          <div class="flex items-center gap-2">
            <Tag v-if="file.category">{{ file.category }}</Tag>
            <span class="font-medium">{{ file.name }}</span>
            <button
              type="button"
              data-testid="download-action"
              class="ml-auto rounded-md border px-3 py-1 text-sm disabled:opacity-60"
              :disabled="downloadingId === file.id"
              :aria-label="t('downloads.downloadFile', { name: file.name })"
              @click="download(file)"
            >
              {{ downloadingId === file.id ? t("downloads.preparing") : t("downloads.download") }}
            </button>
          </div>
          <p v-if="file.description" class="mt-1 text-sm opacity-70">{{ file.description }}</p>
          <p class="mt-1 text-xs opacity-60">
            {{ formatSize(file.file_size) }} · {{ t("downloads.downloadCount", { count: file.download_count }) }}
          </p>
        </li>
        <li v-if="files.length === 0" data-testid="downloads-empty" class="text-sm opacity-70">
          {{ t("downloads.empty") }}
        </li>
      </ul>
    </div>
  </ConfigProvider>
</template>
