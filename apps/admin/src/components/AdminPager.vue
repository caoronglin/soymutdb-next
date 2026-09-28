<template>
  <nav class="flex flex-wrap items-center justify-between gap-3" :aria-label="t('common.pagination')">
    <Button
      size="small"
      :disabled="page <= 1"
      :data-testid="`${testidPrefix}-prev`"
      @click="page -= 1"
    >
      {{ t("common.previous") }}
    </Button>
    <span class="text-sm text-muted-foreground" :data-testid="`${testidPrefix}-page`">
      {{ page }} / {{ lastPage }}
    </span>
    <Button
      size="small"
      :disabled="page >= lastPage"
      :data-testid="`${testidPrefix}-next`"
      @click="page += 1"
    >
      {{ t("common.next") }}
    </Button>
  </nav>
</template>

<script setup lang="ts">
import { Button } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Shared pager for every server-paginated list.
 *
 * `page` is a model so the caller keeps ownership of its own page state (and of
 * resetting it when a filter changes) while the control stays identical
 * everywhere.
 */
defineProps<{ lastPage: number; testidPrefix: string }>();
const page = defineModel<number>({ required: true });
</script>
