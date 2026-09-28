<template>
  <div class="admin-page">
    <AdminPageHeader
      :title="t('common.notFound')"
      :description="t('common.notFoundDescription')"
    >
      <template #actions>
        <RouterLink to="/" class="admin-link" data-testid="not-found-home">
          {{ t("common.goHome") }}
        </RouterLink>
      </template>
    </AdminPageHeader>
  </div>
</template>

<script setup lang="ts">
import AdminPageHeader from "../components/AdminPageHeader.vue";
import { t } from "../lib/i18n";
</script>
