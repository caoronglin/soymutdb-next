<script setup lang="ts">
import { useQueries } from "@tanstack/vue-query";
import { computed, ref, toValue, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { getVariantDetail, type VariantDetail } from "@soymutdb/api-client";
import { formatPosition, jbrowseUrl } from "@soymutdb/shared/genomics";
import { Button } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
import { useSiteContextStore } from "../stores/site-context";

/**
 * Variant comparison.
 *
 * The previous React page compared a hard-coded list of demo variants, which is
 * not a database feature: it answered the same thing no matter what the release
 * contained. This version compares **real variant ids** taken from the URL
 * (`?ids=...`), fetched one by one, and states plainly which of them do not
 * exist in the active release instead of quietly dropping them. The comparison
 * set is capped, and the ids stay in the URL so a comparison is shareable and
 * reloadable.
 */
const MAX_COMPARE = 4;

const route = useRoute();
const router = useRouter();
const site = useSiteContextStore();

const draft = ref("");

const ids = computed<string[]>(() => {
  const raw = route.query.ids;
  const value = Array.isArray(raw) ? raw.join(",") : typeof raw === "string" ? raw : "";
  return value
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean)
    .slice(0, MAX_COMPARE);
});

watch(ids, (value) => {
  draft.value = value.join(", ");
}, { immediate: true });

const results = useQueries({
  queries: computed(() =>
    ids.value.map((variantId) => ({
      queryKey: ["variant", variantId, site.releaseId, site.siteVariant],
      queryFn: () => getVariantDetail(variantId, site.releaseId ?? undefined),
      staleTime: 60_000,
    })),
  ),
});

const isLoading = computed(() => results.value.some((query) => toValue(query.isPending)));
const variants = computed<VariantDetail[]>(() =>
  results.value
    .map((query) => toValue(query.data))
    .filter((variant): variant is VariantDetail => Boolean(variant)),
);
const missing = computed(() =>
  ids.value.filter((_, index) => toValue(results.value[index]?.isError) === true),
);

/** Rows of the comparison table, so adding a field is one line. */
const FIELDS: ReadonlyArray<{ key: keyof VariantDetail; label: string; format?: (value: unknown) => string }> = [
  { key: "chromosome", label: "Chromosome" },
  { key: "position", label: "Position", format: (value) => formatPosition(value as number) },
  { key: "ref_allele", label: "Ref" },
  { key: "alt_allele", label: "Alt" },
  { key: "variant_type", label: "Type" },
  { key: "impact", label: "Impact" },
  { key: "consequence", label: "Consequence" },
  { key: "gene_id", label: "Gene" },
  { key: "hgvs_c", label: "HGVS (c.)" },
  { key: "hgvs_p", label: "HGVS (p.)" },
  { key: "assembly_id", label: "Assembly" },
  { key: "release_id", label: "Release" },
];

function cell(variant: VariantDetail, field: (typeof FIELDS)[number]): string {
  const value = variant[field.key];
  if (value === null || value === undefined || value === "") return "—";
  return field.format ? field.format(value) : String(value);
}

function apply() {
  const next = draft.value
    .split(/[\s,]+/)
    .map((id) => id.trim())
    .filter(Boolean)
    .slice(0, MAX_COMPARE);
  void router.replace({ path: "/compare", query: next.length ? { ids: next.join(",") } : {} });
}
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-7xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("compare.title") }}</h1>
      <p class="mt-1 max-w-3xl text-sm opacity-70">{{ t("compare.subtitle") }}</p>

      <form class="mt-6 flex flex-wrap items-end gap-3" role="search" @submit.prevent="apply">
        <label class="text-sm opacity-70">
          {{ t("compare.variantIds") }}
          <input
            v-model="draft"
            class="mt-1 w-80 rounded-md border bg-background px-2 py-1.5 font-mono text-sm"
            :placeholder="t('compare.placeholder')"
            data-testid="compare-ids"
          />
        </label>
        <Button html-type="submit" data-testid="compare-submit">
          {{ t("common.apply") }}
        </Button>
        <span class="text-xs opacity-60">{{ t("compare.limit", { max: MAX_COMPARE }) }}</span>
      </form>

      <p v-if="isLoading" data-testid="compare-loading" class="mt-6 text-sm opacity-70">
        {{ t("common.loading") }}
      </p>
      <p v-else-if="ids.length === 0" data-testid="compare-idle" class="mt-6 text-sm opacity-70">
        {{ t("compare.subtitle") }}
      </p>
      <template v-else>
        <p
          v-if="missing.length"
          data-testid="compare-missing"
          class="mt-4 rounded-md border border-amber-500/40 p-3 text-sm"
          role="status"
        >
          {{ t("compare.notFound") }} <span class="font-mono">{{ missing.join(", ") }}</span>
        </p>
        <p v-if="variants.length === 0" data-testid="compare-empty" class="mt-6 text-sm opacity-70">
          {{ t("compare.noRows") }}
        </p>
        <table v-else class="mt-6 w-full text-sm" data-testid="compare-table">
          <thead class="text-left opacity-60">
            <tr>
              <th scope="col" class="py-2">{{ t("compare.field") }}</th>
              <th v-for="variant in variants" :key="variant.variant_id" scope="col" class="py-2 font-mono">
                {{ variant.variant_id }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="field in FIELDS" :key="String(field.key)" class="border-t">
              <th scope="row" class="py-2 text-left font-medium">{{ field.label }}</th>
              <td v-for="variant in variants" :key="variant.variant_id" class="py-2 font-mono">
                <a
                  v-if="field.key === 'gene_id' && variant.gene_id"
                  :href="`/genes/${variant.gene_id}?assembly=${encodeURIComponent(String(variant.assembly_id ?? ''))}`"
                  class="underline"
                >
                  {{ cell(variant, field) }}
                </a>
                <span v-else-if="field.key === 'position'">
                  <a
                    class="underline"
                    :href="jbrowseUrl({ chromosome: variant.chromosome, start: variant.position, end: variant.position }, String(variant.assembly_id ?? ''))"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {{ cell(variant, field) }}
                  </a>
                </span>
                <span v-else>{{ cell(variant, field) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </template>
    </div>
  </PortalLayout>
</template>
