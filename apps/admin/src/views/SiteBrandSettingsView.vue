<template>
  <div class="admin-page">
    <AdminPageHeader :title="t('admin.brand.title')" :description="t('admin.brand.description')">
      <template #meta>
        <div class="admin-segmented mt-3" role="tablist" :aria-label="t('admin.brand.title')">
          <button
            v-for="option in VARIANTS"
            :key="option"
            type="button"
            role="tab"
            :aria-selected="variant === option"
            :data-testid="'brand-variant-' + option"
            @click="variant = option"
          >
            {{ option === "external" ? t("admin.brand.variantExternal") : t("admin.brand.variantInternal") }}
          </button>
        </div>
        <p class="mt-2 max-w-2xl text-xs text-muted-foreground">{{ t("admin.brand.variantHint") }}</p>
      </template>
    </AdminPageHeader>

    <AdminState v-if="query.isPending.value" state="loading" testid="brand-loading" />
    <AdminState
      v-else-if="query.isError.value"
      state="error"
      testid="brand-load-error"
      :title="t('admin.brand.loadError')"
    >
      <template #actions>
        <Button size="small" data-testid="brand-retry" @click="query.refetch()">
          {{ t("common.retry") }}
        </Button>
      </template>
    </AdminState>

    <AdminCard v-else class="max-w-2xl">
      <form class="grid gap-3" data-testid="brand-form" @submit.prevent="saveMutation.mutate()">
        <p class="text-xs text-muted-foreground">
          {{ t("admin.brand.version") }}: {{ query.data.value?.version ?? 0 }}
        </p>

        <label class="admin-field">
          {{ t("admin.brand.nameZh") }}
          <input
            v-model="nameZh"
            type="text"
            required
            maxlength="120"
            class="admin-control"
            data-testid="brand-name-zh"
          />
        </label>
        <label class="admin-field">
          {{ t("admin.brand.nameEn") }}
          <input
            v-model="nameEn"
            type="text"
            required
            maxlength="120"
            class="admin-control"
            data-testid="brand-name-en"
          />
        </label>
        <label class="admin-field">
          {{ t("admin.brand.iconUrl") }}
          <input
            v-model="iconUrl"
            type="url"
            class="admin-control admin-control--mono"
            data-testid="brand-icon-url"
            @input="iconDirty = true"
          />
        </label>
        <p class="text-xs text-muted-foreground">{{ t("admin.brand.iconHelp") }}</p>

        <div class="flex items-center gap-3">
          <img
            v-if="previewIconSrc"
            :src="previewIconSrc"
            :alt="t('admin.brand.preview')"
            class="size-10 rounded-md border border-border object-contain"
            data-testid="brand-icon-preview"
          />
          <span v-else class="text-xs text-muted-foreground" data-testid="brand-icon-empty">
            {{ t("admin.brand.noIcon") }}
          </span>
          <Button
            html-type="button"
            size="small"
            :disabled="!iconUrl"
            data-testid="brand-icon-clear"
            @click="clearIcon"
          >
            {{ t("admin.brand.clearIcon") }}
          </Button>
        </div>

        <p v-if="noticeMessage" class="admin-state" data-testid="brand-notice">
          {{ noticeMessage }}
        </p>
        <p v-if="conflictMessage" class="admin-state admin-state--error" data-testid="brand-conflict">
          {{ conflictMessage }}
        </p>
        <p v-if="errorMessage" class="admin-state admin-state--error" data-testid="brand-error">
          {{ errorMessage }}
        </p>

        <div>
          <Button
            type="primary"
            html-type="submit"
            :disabled="saveMutation.isPending.value"
            data-testid="brand-save"
          >
            {{ saveMutation.isPending.value ? t("common.loading") : t("common.save") }}
          </Button>
        </div>
      </form>
    </AdminCard>
  </div>
</template>

<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";

import {
  ApiError,
  getAdminSiteBranding,
  patchAdminSiteBranding,
  type AdminSiteBranding,
} from "@soymutdb/api-client";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import { t } from "../lib/i18n";

/**
 * Per-variant site branding.
 *
 * Values live in the versioned `system_settings` store under
 * `brand_external` / `brand_internal` and are read back through the admin API,
 * which maps the icon to a verified media asset. Saving sends the revision the
 * form was loaded from; a rejected revision (409) means another operator saved
 * first, so the form reloads the newest values instead of overwriting them.
 */
type Variant = "external" | "internal";

const VARIANTS: readonly Variant[] = ["external", "internal"];

const queryClient = useQueryClient();
const variant = ref<Variant>("external");
const nameZh = ref("");
const nameEn = ref("");
const iconUrl = ref("");
const iconDirty = ref(false);
const errorMessage = ref("");
const noticeMessage = ref("");
const conflictMessage = ref("");

const query = useQuery({
  queryKey: computed(() => ["admin", "site-brand", variant.value]),
  queryFn: () => getAdminSiteBranding(variant.value),
  staleTime: 0,
  retry: false,
});

watch(
  () => toValue(query.data),
  (brand: AdminSiteBranding | undefined) => {
    if (!brand) return;
    nameZh.value = brand.values.name_zh;
    nameEn.value = brand.values.name_en;
    iconUrl.value = brand.values.icon_url ?? "";
    iconDirty.value = false;
    noticeMessage.value = "";
    conflictMessage.value = "";
    errorMessage.value = "";
  },
  { immediate: true },
);

const saveMutation = useMutation({
  mutationFn: () => {
    const values: { name_zh?: string; name_en?: string; icon_url?: string | null } = {
      name_zh: nameZh.value.trim(),
      name_en: nameEn.value.trim(),
    };
    if (iconDirty.value) values.icon_url = iconUrl.value.trim() ? iconUrl.value.trim() : null;
    return patchAdminSiteBranding(variant.value, toValue(query.data)?.version ?? 0, values);
  },
  onSuccess: (brand: AdminSiteBranding) => {
    queryClient.setQueryData(["admin", "site-brand", variant.value], brand);
    noticeMessage.value = t("admin.brand.saveSuccess");
    errorMessage.value = "";
    conflictMessage.value = "";
    void queryClient.invalidateQueries({ queryKey: ["admin", "site-brand"] });
  },
  onError: (error: unknown) => {
    noticeMessage.value = "";
    if (error instanceof ApiError && error.status === 409) {
      // Another operator saved first. Keep the typed values but offer the
      // reloaded revision so the next save is based on what is stored.
      conflictMessage.value = t("admin.brand.conflict");
      void queryClient.invalidateQueries({ queryKey: ["admin", "site-brand"] });
    } else {
      errorMessage.value = t("admin.brand.saveError");
    }
  },
});

function clearIcon(): void {
  iconUrl.value = "";
  iconDirty.value = true;
}

/** Only an absolute HTTP(S) URL is worth rendering as an `<img src>`. */
const previewIconSrc = computed<string | null>(() => {
  const value = iconUrl.value.trim();
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? value : null;
  } catch {
    return null;
  }
});
</script>
