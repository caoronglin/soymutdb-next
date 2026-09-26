<script setup lang="ts">
import { useRoute, useRouter } from "vue-router";
import { t } from "../lib/i18n";

const route = useRoute();
const router = useRouter();
</script>

<template>
  <main class="notfound">
    <h1>404</h1>
    <p>{{ t("common.noRouteFor", { path: route.fullPath }) }}</p>
    <button type="button" @click="router.push({ name: 'home' })">{{ t("common.backToHome") }}</button>
  </main>
</template>

<style scoped>
.notfound {
  padding: 2rem;
  font-family: system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
}
</style>
