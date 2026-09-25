<script setup lang="ts">
import { onMounted } from "vue";
import { RouterView, useRoute } from "vue-router";

import AdminLayout from "./components/AdminLayout.vue";
import { useAuth } from "./lib/auth";

const route = useRoute();
const auth = useAuth();

onMounted(() => {
  void auth.restore();
});

// The login page renders outside the console chrome: a signed-out operator has
// no navigation to use, and showing a sidebar whose every link bounces back to
// /login is a worse answer than not showing it.
</script>

<template>
  <RouterView v-if="route.name === 'login'" />
  <AdminLayout v-else>
    <RouterView />
  </AdminLayout>
</template>
