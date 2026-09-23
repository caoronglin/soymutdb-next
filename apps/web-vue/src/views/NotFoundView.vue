<script setup lang="ts">
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
</script>

<template>
  <main class="notfound">
    <h1>404</h1>
    <p>No route for <code>{{ route.fullPath }}</code>.</p>
    <button type="button" @click="router.push({ name: 'home' })">Back to home</button>
  </main>
</template>

<style scoped>
.notfound {
  padding: 2rem;
  font-family: system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
}
</style>
