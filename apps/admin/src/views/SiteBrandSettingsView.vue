<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";

import {
  ApiError,
  getAdminSiteBranding,
  patchAdminSiteBranding,
  type AdminSiteBranding,
} from "@soymutdb/api-client";
import { Button, ConfigProvider, createThemeConfig } from "@soymutdb/ui-vue";

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

function previewIcon(): string | null {
  const value = iconUrl.value.trim();
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? value : null;
  } catch {
    return null;
  }
}
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div>
      <h1 class="text-xl font-semibold">{{ t("admin.brand.title") }}</h1>
      <p class="mt-1 max-w-2xl text-sm opacity-70">{{ t("admin.brand.description") }}</p>

      <div class="mt-4 flex flex-wrap gap-2" role="tablist" :aria-label="t('admin.brand.title')">
        <button
          v-for="option in VARIANTS"
          :key="option"
          type="button"
          role="tab"
          :aria-selected="variant === option"
          class="rounded-md border px-3 py-1.5 text-sm"
          :class="variant === option
            ? 'border-primary bg-primary/10 font-medium text-primary'
            : 'border-border text-muted-foreground hover:bg-muted'"
          :data-testid="'brand-variant-' + option"
          @click="variant = option"
        >
          {{ option === "external" ? t("admin.brand.variantExternal") : t("admin.brand.variantInternal") }}
        </button>
      </div>
      <p class="mt-2 max-w-2xl text-xs opacity-70">{{ t("admin.brand.variantHint") }}</p>

      <p v-if="query.isPending.value" data-testid="brand-loading" class="mt-4 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <p
        v-else-if="query.isError.value"
        data-testid="brand-load-error"
        class="mt-4 text-sm text-red-700"
      >
        {{ t("admin.brand.loadError") }}
      </p>
      <form
        v-else
        class="mt-4 grid max-w-xl gap-3 rounded-lg border border-border bg-card p-4"
        data-testid="brand-form"
        @submit.prevent="saveMutation.mutate()"
      >
        <p class="text-xs opacity-70">
          {{ t("admin.brand.version") }}: {{ query.data.value?.version ?? 0 }}
        </p>

        <label class="text-sm">
          <span class="opacity-70">{{ t("admin.brand.nameZh") }}</span>
          <input
            v-model="nameZh"
            type="text"
            required
            maxlength="120"
            class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            data-testid="brand-name-zh"
          />
        </label>
        <label class="text-sm">
          <span class="opacity-70">{{ t("admin.brand.nameEn") }}</span>
          <input
            v-model="nameEn"
            type="text"
            required
            maxlength="120"
            class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            data-testid="brand-name-en"
          />
        </label>
        <label class="text-sm">
          <span class="opacity-70">{{ t("admin.brand.iconUrl") }}</span>
          <input
            v-model="iconUrl"
            type="url"
            class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs"
            data-testid="brand-icon-url"
            @input="iconDirty = true"
          />
        </label>
        <p class="text-xs opacity-70">{{ t("admin.brand.iconHelp") }}</p>

        <div class="flex items-center gap-3">
          <img
            v-if="previewIcon()"
            :src="previewIcon() ?? undefined"
            :alt="t('admin.brand.preview')"
            class="size-10 rounded-md border border-border object-contain"
            data-testid="brand-icon-preview"
          />
          <span v-else class="text-xs opacity-70" data-testid="brand-icon-empty">
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

        <p
          v-if="noticeMessage"
          data-testid="brand-notice"
          class="rounded-md border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-800"
        >
          {{ noticeMessage }}
        </p>
        <p
          v-if="conflictMessage"
          data-testid="brand-conflict"
          class="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800"
        >
          {{ conflictMessage }}
        </p>
        <p
          v-if="errorMessage"
          data-testid="brand-error"
          class="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
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
    </div>
  </ConfigProvider>
</template>
