<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { getAssemblies, type AssemblyInfo } from "@soymutdb/api-client";
import { queryKeys } from "@soymutdb/query-keys";

import { useSiteContextStore } from "../stores/site-context";

const site = useSiteContextStore();

// First real server-state read (Checkpoint C). Assemblies carry the genome
// namespace context (v4/v5, DB-CORE-3) the whole database experience keys on, so
// the home surfaces them via the neutral api-client + query-keys seam under
// TanStack Vue Query. The cache key is scoped by the site variant (DB-CORE-6).
const { data, isPending, isError, error } = useQuery<AssemblyInfo[]>({
  queryKey: queryKeys.assemblies.all(),
  queryFn: () => getAssemblies(),
});
</script>

<template>
  <main class="home">
    <header class="home-header">
      <h1>SoyMutDB</h1>
      <nav aria-label="Primary">
        <RouterLink to="/">Home</RouterLink>
      </nav>
    </header>

    <p data-testid="site-variant">Site variant: {{ site.siteVariant }}</p>

    <section aria-labelledby="assemblies-heading">
      <h2 id="assemblies-heading">Assemblies</h2>
      <p v-if="isPending" data-testid="assemblies-loading">Loading assemblies…</p>
      <p v-else-if="isError" data-testid="assemblies-error">
        Could not load assemblies: {{ (error as Error)?.message ?? "unknown error" }}
      </p>
      <p v-else-if="!data || data.length === 0" data-testid="assemblies-empty">
        No assemblies are available.
      </p>
      <ul v-else data-testid="assemblies-list">
        <li v-for="assembly in data" :key="String(assembly.id)">
          <button type="button" @click="site.setAssembly(assembly.name)">
            {{ assembly.name }} · {{ assembly.version }} · {{ assembly.species }}
            <span v-if="assembly.is_default"> (default)</span>
          </button>
        </li>
      </ul>
    </section>

    <section class="home-note">
      <p>
        Vue portal (Checkpoint C): first real read via the neutral api-client +
        query-keys seam. Identifier search and entity routes migrate next.
      </p>
    </section>
  </main>
</template>

<style scoped>
.home {
  font-family: system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
  padding: 2rem;
}
.home-header {
  display: flex;
  align-items: baseline;
  gap: 1rem;
}
</style>
