<script setup lang="ts">
import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <main class="mx-auto max-w-4xl p-8">
      <RouterLink to="/" class="text-sm underline opacity-70">Home</RouterLink>
      <h1 class="mt-2 text-2xl font-semibold">Research tools</h1>
      <p class="mt-2 max-w-2xl text-sm opacity-70">
        Extract assembly-scoped reference sequences for gene lists or genomic regions.
      </p>

      <RouterLink
        to="/tools/seqfetch"
        class="mt-6 block rounded-lg border p-5 transition hover:bg-black/5"
        data-testid="seqfetch-tool-link"
      >
        <h2 class="font-medium">Sequence fetch (SeqFetch)</h2>
        <p class="mt-1 text-sm opacity-70">
          Download FASTA for up to 200 genes or one 1-based inclusive region from a selected assembly.
        </p>
        <span class="mt-3 inline-block text-sm underline">Open tool</span>
      </RouterLink>

      <RouterLink
        to="/tools/exppattern"
        class="mt-4 block rounded-lg border p-5 transition hover:bg-black/5"
        data-testid="exppattern-tool-link"
      >
        <h2 class="font-medium">Expression pattern</h2>
        <p class="mt-1 text-sm opacity-70">
          Compare expression across libraries for up to 50 genes in one selected assembly.
        </p>
        <span class="mt-3 inline-block text-sm underline">Open tool</span>
      </RouterLink>

      <RouterLink
        to="/tools/enrichment"
        class="mt-4 block rounded-lg border p-5 transition hover:bg-black/5"
        data-testid="enrichment-tool-link"
      >
        <h2 class="font-medium">GO / KEGG enrichment</h2>
        <p class="mt-1 text-sm opacity-70">
          Run over-representation or ranked enrichment analysis with assembly-scoped annotations.
        </p>
        <span class="mt-3 inline-block text-sm underline">Open tool</span>
      </RouterLink>
    </main>
  </ConfigProvider>
</template>
