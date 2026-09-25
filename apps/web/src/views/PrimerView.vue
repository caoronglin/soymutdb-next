<script setup lang="ts">
import { useMutation } from "@tanstack/vue-query";
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, toValue } from "vue";

import {
  seqFetchRegion,
  type AssemblyInfo,
  type SeqFetchResponse,
} from "@soymutdb/api-client";
import { parseRegion, SOYBEAN_CHROMOSOMES } from "@soymutdb/shared/genomics";
import { designPrimerPair, parseFasta, type PrimerPair } from "@soymutdb/shared/primer-design";
import { Button } from "@soymutdb/ui-vue";

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
import { assembliesQueryOptions } from "../lib/query-options";

/**
 * Primer design — pure-frontend heuristic primer-pair design (no Primer3).
 *
 * The template is either pasted or fetched from the reference through the
 * assembly-scoped SeqFetch region endpoint, so the designed primers always
 * belong to the selected assembly. Results are ranked pairs with Tm/GC/clamp
 * and a JBrowse deep link; the page states that wet-lab validation is still
 * required.
 */
const assembliesQuery = useQuery(assembliesQueryOptions());
const assemblies = computed<AssemblyInfo[]>(() => toValue(assembliesQuery.data) ?? []);

const mode = ref<"region" | "paste">("region");
const draftAssemblyId = ref("");
const chromosome = ref("chr01");
const start = ref("1");
const end = ref("1000");
const pasted = ref("");
const pairs = ref<PrimerPair[] | null>(null);
const sourceLabel = ref<string | null>(null);
const errorMessage = ref("");

const defaultAssemblyId = computed(() => {
  const fallback = assemblies.value.find((item) => item.is_default) ?? assemblies.value[0];
  return fallback ? String(fallback.id) : "";
});
const assemblyId = computed(() => draftAssemblyId.value || defaultAssemblyId.value);
const selectedAssembly = computed(() =>
  assemblies.value.find((item) => String(item.id) === assemblyId.value),
);

const fetchMutation = useMutation({
  mutationFn: async (): Promise<{ template: string; label: string }> => {
    if (mode.value === "paste") {
      const records = parseFasta(pasted.value);
      const sequence = records.map((record) => record.sequence).join("");
      if (!sequence) throw new Error("empty");
      return { template: sequence, label: t("search.primer.modePaste") };
    }
    const region = parseRegion(`${chromosome.value}:${start.value}-${end.value}`);
    if (!region) throw new Error("region");
    const response: SeqFetchResponse = await seqFetchRegion(
      selectedAssembly.value?.name ?? "",
      `${region.chromosome}:${region.start}-${region.end}`,
    );
    const records = parseFasta(response.sequence ?? "");
    return {
      template: records.map((record) => record.sequence).join(""),
      label: `${selectedAssembly.value?.name ?? ""} · ${region.chromosome}:${region.start}-${region.end}`,
    };
  },
  onSuccess: (data) => {
    const designed = designPrimerPair(data.template);
    pairs.value = designed;
    sourceLabel.value = data.label;
    errorMessage.value = designed.length === 0 ? t("search.primer.noPairs") : "";
  },
  onError: () => {
    pairs.value = null;
    sourceLabel.value = null;
    errorMessage.value =
      mode.value === "paste" ? t("search.primer.noSequence") : t("search.primer.fetchFailed");
  },
});

const isPending = computed(() => toValue(fetchMutation.isPending));
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-5xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("search.primer.title") }}</h1>
      <p class="mt-1 max-w-2xl text-sm opacity-70">{{ t("search.primer.subtitle") }}</p>

      <div class="mt-6 grid gap-4 lg:grid-cols-2">
        <form class="grid content-start gap-4 rounded-lg border p-5" @submit.prevent="fetchMutation.mutate()">
          <div class="flex gap-2">
            <Button
              :type="mode === 'region' ? 'primary' : 'default'"
              data-testid="primer-mode-region"
              @click="mode = 'region'"
            >
              {{ t("search.primer.modeRegion") }}
            </Button>
            <Button
              :type="mode === 'paste' ? 'primary' : 'default'"
              data-testid="primer-mode-paste"
              @click="mode = 'paste'"
            >
              {{ t("search.primer.modePaste") }}
            </Button>
          </div>

          <template v-if="mode === 'region'">
            <label class="text-sm opacity-70">
              {{ t("search.genes.assembly") }}
              <select
                v-model="draftAssemblyId"
                class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
                data-testid="primer-assembly"
              >
                <option v-for="item in assemblies" :key="String(item.id)" :value="String(item.id)">
                  {{ item.name }}{{ item.is_default ? " · default" : "" }}
                </option>
              </select>
            </label>
            <label class="text-sm opacity-70">
              {{ t("search.location.chromosome") }}
              <select v-model="chromosome" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5">
                <option v-for="name in SOYBEAN_CHROMOSOMES" :key="name" :value="name">{{ name }}</option>
              </select>
            </label>
            <div class="grid grid-cols-2 gap-3">
              <label class="text-sm opacity-70">
                {{ t("search.location.start") }}
                <input v-model="start" type="number" min="1" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono" />
              </label>
              <label class="text-sm opacity-70">
                {{ t("search.location.end") }}
                <input v-model="end" type="number" min="1" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono" />
              </label>
            </div>
          </template>
          <label v-else class="text-sm opacity-70">
            {{ t("search.primer.sequence") }}
            <textarea
              v-model="pasted"
              rows="6"
              class="mt-1 w-full rounded-md border bg-background p-3 font-mono text-sm"
              data-testid="primer-template"
            />
          </label>

          <Button html-type="submit" :disabled="isPending" data-testid="primer-submit">
            {{ isPending ? t("common.loading") : t("search.primer.results") }}
          </Button>
        </form>

        <section aria-live="polite" class="rounded-lg border p-5" data-testid="primer-result">
          <p v-if="errorMessage" class="text-sm text-red-700" role="alert" data-testid="primer-error">
            {{ errorMessage }}
          </p>
          <p v-else-if="!pairs" class="text-sm opacity-70">{{ t("search.primer.howItWorks") }}</p>
          <template v-else>
            <p class="text-sm opacity-70" data-testid="primer-source">{{ sourceLabel }}</p>
            <ul class="mt-3 grid gap-3">
              <li
                v-for="(pair, index) in pairs"
                :key="index"
                class="rounded-md border p-3"
                :data-testid="'primer-pair-' + index"
              >
                <p class="text-xs opacity-70">
                  {{ t("search.primer.score") }} {{ pair.score }} · {{ t("search.primer.product") }}
                  {{ pair.productLen }} bp
                </p>
                <p class="mt-1 font-mono text-sm" data-testid="primer-forward">F {{ pair.forward.seq }}</p>
                <p class="font-mono text-sm" data-testid="primer-reverse">R {{ pair.reverse.seq }}</p>
                <p class="mt-1 text-xs opacity-70">
                  Tm {{ pair.forward.tm.toFixed(1) }} / {{ pair.reverse.tm.toFixed(1) }} °C · GC
                  {{ pair.forward.gc }}% / {{ pair.reverse.gc }}%
                </p>
              </li>
            </ul>
            <p class="mt-3 text-xs opacity-70">{{ t("search.primer.disclaimer") }}</p>
          </template>
        </section>
      </div>
    </div>
  </PortalLayout>
</template>
