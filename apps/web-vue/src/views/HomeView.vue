<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";

import { useSiteContextStore } from "../stores/site-context";

const site = useSiteContextStore();

// Server-state read goes through TanStack Vue Query (D2), never Pinia. This is
// a placeholder proving the query client is wired; the real portal reads
// (search/genes/variants via @soymutdb/api-client) replace it per route in
// Phase F. Cache keys must carry site-variant/release/assembly (DB-CORE-6).
const { data, isPending } = useQuery({
  queryKey: ["health", site.siteVariant],
  queryFn: async () => ({ status: "ok" }),
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
    <p data-testid="query-status">
      API client: {{ isPending ? "loading…" : (data?.status ?? "unknown") }}
    </p>
    <section class="home-note">
      <p>
        Vue portal foundation (Checkpoint B): router + Pinia + Vue Query wired.
        Database search and entity routes migrate here in later commits.
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
