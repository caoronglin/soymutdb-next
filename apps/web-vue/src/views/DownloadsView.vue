<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import { getDownloadFiles, type DownloadFile } from "@soymutdb/api-client";
import { ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

// Data downloads (Phase F). Lists downloadable artifacts via the neutral
// api-client, scoped by category. file_size/dates are displayed; downloads go
// through presigned URLs (never a leaked direct bucket link). The cache key is
// static per category (this endpoint is not per release/assembly, so no
// release/assembly scoping is added here — DB-CORE-6 scoping applies to
// biological search, not the content catalogue).
const category = ref<string>("");
const isLoading = computed(() => toValue(query.isLoading));
const isError = computed(() => toValue(query.isError));
const files = computed<DownloadFile[]>(() => toValue(query.data) ?? []);

const query = useQuery({
  queryKey: computed(() => ["downloads", category.value || null] as const),
  queryFn: () => getDownloadFiles(category.value || undefined),
  staleTime: 60_000,
});

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
      <p class="text-sm opacity-70"><RouterLink to="/" class="underline">Home</RouterLink></p>
      <h1 class="mt-2 text-2xl font-semibold">Downloads</h1>
      <p class="mt-2 text-sm opacity-70">
        Download SoyMutDB data files. Files are served through short-lived presigned URLs.
      </p>

      <div v-if="isLoading" data-testid="downloads-loading" class="mt-6 grid gap-3">
        <div v-for="index in 4" :key="index" class="h-16 w-full rounded bg-black/5" />
      </div>
      <div v-else-if="isError" data-testid="downloads-error" class="mt-6 rounded border border-red-300 p-5">
        <p class="font-medium">Could not load downloads.</p>
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
          </div>
          <p v-if="file.description" class="mt-1 text-sm opacity-70">{{ file.description }}</p>
          <p class="mt-1 text-xs opacity-60">
            {{ formatSize(file.file_size) }} · {{ file.download_count }} downloads
          </p>
        </li>
        <li v-if="files.length === 0" data-testid="downloads-empty" class="text-sm opacity-70">
          No downloads available.
        </li>
      </ul>
    </div>
  </ConfigProvider>
</template>
