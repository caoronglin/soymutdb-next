<template>
  <ConfigProvider :theme="createThemeConfig({ dark: theme === 'dark' })">
    <RouterView v-if="route.name === 'login'" />
    <AdminLayout v-else>
      <RouterView />
    </AdminLayout>
  </ConfigProvider>
</template>

<script setup lang="ts">
import { onMounted } from "vue";
import { RouterView, useRoute } from "vue-router";

import { ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

import AdminLayout from "./components/AdminLayout.vue";
import { useAuth } from "./lib/auth";
import { useAdminTheme } from "./lib/theme";

/**
 * One ConfigProvider for the whole console.
 *
 * Every view used to mount its own, which meant N nested providers (and N
 * copies of the theme) with no single place that knew the active theme. Mounting
 * it here also lets the dark-mode toggle actually reach the AntD tokens instead
 * of only repainting Tailwind classes.
 *
 * The login page renders outside the console chrome: a signed-out operator has
 * no navigation to use, and a sidebar whose every link bounces back to /login is
 * a worse answer than no sidebar.
 */
const route = useRoute();
const auth = useAuth();
const { theme } = useAdminTheme();

onMounted(() => {
  void auth.restore();
});
</script>
