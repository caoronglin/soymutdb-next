<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";

import type { AssemblyInfo } from "@soymutdb/api-client";
import { cn } from "@soymutdb/shared/cn";
// Business code imports UI primitives ONLY from the facade (plan D4), never
// from antdv-next directly.
import { Button, ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { assembliesQueryOptions } from "../lib/query-options";
import { useSiteContextStore } from "../stores/site-context";

const site = useSiteContextStore();

// Assembly reference data through the shared queryOptions factory: the page
// never hand-writes a key that could drift from the request.
const query = useQuery(assembliesQueryOptions());

const isPending = computed(() => toValue(query.isPending));
const isError = computed(() => toValue(query.isError));
const error = computed(() => toValue(query.error));
const assemblies = computed<AssemblyInfo[]>(() => toValue(query.data) ?? []);
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <main :class="cn('mx-auto max-w-3xl p-8')">
      <header class="flex items-baseline gap-4">
        <h1 class="text-2xl font-semibold">SoyMutDB</h1>
        <nav aria-label="Primary">
          <RouterLink to="/" class="text-sm underline">Home</RouterLink>
        </nav>
      </header>

      <p class="mt-2 text-sm opacity-70" data-testid="site-variant">
        Site variant: {{ site.siteVariant }}
      </p>

      <section class="mt-6" aria-labelledby="assemblies-heading">
        <h2 id="assemblies-heading" class="text-lg font-medium">Assemblies</h2>
        <p v-if="isPending" data-testid="assemblies-loading">Loading assemblies…</p>
        <p v-else-if="isError" data-testid="assemblies-error" class="text-red-600">
          Could not load assemblies: {{ (error as Error)?.message ?? "unknown error" }}
        </p>
        <p v-else-if="assemblies.length === 0" data-testid="assemblies-empty">
          No assemblies are available.
        </p>
        <ul v-else data-testid="assemblies-list" class="mt-2 flex flex-col gap-2">
          <li v-for="assembly in assemblies" :key="String(assembly.id)">
            <Button type="primary" @click="site.setAssembly(assembly.name)">
              {{ assembly.name }} · {{ assembly.version }} · {{ assembly.species }}
              <Tag v-if="assembly.is_default" color="green">default</Tag>
            </Button>
          </li>
        </ul>
      </section>

      <section class="mt-8 text-sm opacity-70">
        <p>
          Vue portal (Checkpoint D): Antdv Next via the @soymutdb/ui-vue facade +
          Tailwind CSS 4 + cn class merge.
        </p>
      </section>
    </main>
  </ConfigProvider>
</template>
