<script setup lang="ts">
// Minimal public-portal shell (Phase D, Checkpoint A). This proves the Vue/Vite
// toolchain builds and previews; the database-first experience (identifier
// search, entity routes, assembly/release context) is migrated per page in later
// commits. It consumes the framework-neutral @soymutdb/shared seam to prove the
// React→Vue shared layer works from a Vue consumer.
import { cn } from "@soymutdb/shared/cn";

declare const __SITE_VARIANT__: "external" | "internal";
const siteVariant = __SITE_VARIANT__;
</script>

<template>
  <main :class="cn('soymutdb-shell')">
    <h1>SoyMutDB</h1>
    <p data-testid="site-variant">Site variant: {{ siteVariant }}</p>
    <p class="shell-note">
      Vue portal shell (Checkpoint A). Database search and entity routes migrate
      here in subsequent commits.
    </p>
  </main>
</template>

<style scoped>
.soymutdb-shell {
  font-family: system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
  padding: 2rem;
}
</style>
