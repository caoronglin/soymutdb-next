<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, reactive, ref, toValue } from "vue";

import {
  createAdminPublication,
  deleteAdminPublication,
  listAdminPublications,
  updateAdminPublication,
  type Publication,
} from "@soymutdb/api-client";
import { Button, ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";

/**
 * Publications CRUD.
 *
 * Delete asks for confirmation and states what will be removed: the row is
 * cited by DOI elsewhere, so an accidental delete is not "just a row". A create
 * or update failure leaves the form values in place so the operator does not
 * retype the abstract to retry.
 */
interface PublicationForm {
  id: string | null;
  title: string;
  title_zh: string;
  authors: string;
  journal: string;
  year: string;
  doi: string;
  pmid: string;
  abstract: string;
  is_featured: boolean;
}

const queryClient = useQueryClient();
const page = ref(1);
const search = ref("");
const pendingDelete = ref<Publication | null>(null);
const errorMessage = ref("");

const emptyForm = (): PublicationForm => ({
  id: null,
  title: "",
  title_zh: "",
  authors: "",
  journal: "",
  year: "",
  doi: "",
  pmid: "",
  abstract: "",
  is_featured: false,
});

const form = reactive<PublicationForm>(emptyForm());

const query = useQuery({
  queryKey: computed(() => ["admin", "publications", page.value, search.value]),
  queryFn: () => listAdminPublications({ page: page.value, page_size: 20, search: search.value || undefined }),
  staleTime: 15_000,
});

const items = computed(() => toValue(query.data)?.items ?? []);
const total = computed(() => toValue(query.data)?.total ?? 0);
const lastPage = computed(() => Math.max(1, Math.ceil(total.value / 20)));

function edit(row: Publication) {
  form.id = row.id;
  form.title = row.title;
  form.title_zh = row.title_zh ?? "";
  form.authors = row.authors;
  form.journal = row.journal ?? "";
  form.year = row.year === null ? "" : String(row.year);
  form.doi = row.doi ?? "";
  form.pmid = row.pmid ?? "";
  form.abstract = row.abstract ?? "";
  form.is_featured = row.is_featured;
}

function reset() {
  Object.assign(form, emptyForm());
  errorMessage.value = "";
}

const saveMutation = useMutation({
  mutationFn: async () => {
    const payload = {
      title: form.title.trim(),
      title_zh: form.title_zh.trim() || null,
      authors: form.authors.trim(),
      journal: form.journal.trim() || null,
      year: form.year.trim() ? Number(form.year) : null,
      doi: form.doi.trim() || null,
      pmid: form.pmid.trim() || null,
      abstract: form.abstract.trim() || null,
      is_featured: form.is_featured,
    };
    return form.id ? updateAdminPublication(form.id, payload) : createAdminPublication(payload);
  },
  onSuccess: () => {
    reset();
    void queryClient.invalidateQueries({ queryKey: ["admin", "publications"] });
  },
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const deleteMutation = useMutation({
  mutationFn: (id: string) => deleteAdminPublication(id),
  onSuccess: () => {
    pendingDelete.value = null;
    void queryClient.invalidateQueries({ queryKey: ["admin", "publications"] });
  },
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});
</script>

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
      <section>
        <h1 class="text-xl font-semibold">{{ t("publications.title") }}</h1>

        <form class="mt-4 flex gap-2" role="search" @submit.prevent="page = 1">
          <input
            v-model="search"
            class="w-64 rounded-md border bg-background px-2 py-1.5 text-sm"
            :placeholder="t('common.search')"
            data-testid="publications-search"
          />
          <Button html-type="submit" size="small">{{ t("common.apply") }}</Button>
        </form>

        <p v-if="query.isPending.value" class="mt-4 text-sm opacity-70">{{ t("common.loading") }}</p>
        <p v-else-if="query.isError.value" class="mt-4 text-sm text-red-700">
          {{ t("common.errorDescription") }}
        </p>
        <p v-else-if="items.length === 0" data-testid="publications-empty" class="mt-4 text-sm opacity-70">
          {{ t("publications.noPublications") }}
        </p>
        <table v-else class="mt-4 w-full text-sm" data-testid="publications-table">
          <thead class="text-left opacity-60">
            <tr>
              <th scope="col" class="py-2">{{ t("publications.title") }}</th>
              <th scope="col" class="py-2">{{ t("publications.year") }}</th>
              <th scope="col" class="py-2">{{ t("common.actions") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in items" :key="row.id" class="border-t" data-testid="publication-row">
              <td class="py-2">
                {{ row.title }}
                <Tag v-if="row.is_featured" color="gold">{{ t("admin.publications.featured") }}</Tag>
              </td>
              <td class="py-2 text-xs opacity-70">{{ row.year ?? "—" }}</td>
              <td class="py-2">
                <button type="button" class="underline" :data-testid="'publication-edit-' + row.id" @click="edit(row)">
                  {{ t("common.edit") }}
                </button>
                <button
                  type="button"
                  class="ms-3 underline text-red-700"
                  :data-testid="'publication-delete-' + row.id"
                  @click="pendingDelete = row"
                >
                  {{ t("common.delete") }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <nav v-if="items.length" class="mt-4 flex items-center gap-3" :aria-label="t('common.pagination')">
          <button
            type="button"
            class="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            :disabled="page <= 1"
            @click="page -= 1"
          >
            {{ t("common.previous") }}
          </button>
          <span class="text-sm opacity-70">{{ page }} / {{ lastPage }}</span>
          <button
            type="button"
            class="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            :disabled="page >= lastPage"
            @click="page += 1"
          >
            {{ t("common.next") }}
          </button>
        </nav>

        <div
          v-if="pendingDelete"
          role="alertdialog"
          aria-labelledby="delete-heading"
          class="mt-4 rounded-md border border-red-400 p-4"
          data-testid="publication-delete-confirm"
        >
          <h2 id="delete-heading" class="text-sm font-medium">{{ t("common.delete") }}</h2>
          <p class="mt-1 text-sm opacity-80">
            {{ pendingDelete.title }}
            <span v-if="pendingDelete.doi" class="ms-1 font-mono text-xs">DOI {{ pendingDelete.doi }}</span>
          </p>
          <div class="mt-3 flex gap-2">
            <Button
              size="small"
              data-testid="publication-delete-confirm-button"
              :disabled="deleteMutation.isPending.value"
              @click="deleteMutation.mutate(pendingDelete.id)"
            >
              {{ t("common.confirm") }}
            </Button>
            <Button size="small" data-testid="publication-delete-cancel" @click="pendingDelete = null">
              {{ t("common.cancel") }}
            </Button>
          </div>
        </div>
      </section>

      <section class="rounded-lg border p-4">
        <h2 class="text-sm font-medium">
          {{ form.id ? t("common.edit") : t("common.save") }}
        </h2>
        <form class="mt-3 grid gap-3" @submit.prevent="saveMutation.mutate()">
          <label class="text-sm opacity-70">
            {{ t("publications.title") }}
            <input v-model="form.title" required class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" data-testid="publication-title" />
          </label>
          <label class="text-sm opacity-70">
            {{ t("publications.authors") }}
            <input v-model="form.authors" required class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" data-testid="publication-authors" />
          </label>
          <div class="grid grid-cols-2 gap-3">
            <label class="text-sm opacity-70">
              {{ t("publications.journal") }}
              <input v-model="form.journal" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" />
            </label>
            <label class="text-sm opacity-70">
              {{ t("publications.year") }}
              <input v-model="form.year" inputmode="numeric" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" />
            </label>
          </div>
          <label class="text-sm opacity-70">
            {{ t("publications.doi") }}
            <input v-model="form.doi" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono text-xs" data-testid="publication-doi" />
          </label>
          <label class="flex items-center gap-2 text-sm">
            <input v-model="form.is_featured" type="checkbox" data-testid="publication-featured" />
            {{ t("admin.publications.featured") }}
          </label>
          <p v-if="errorMessage" role="alert" class="text-sm text-red-700" data-testid="publication-error">
            {{ errorMessage }}
          </p>
          <div class="flex gap-2">
            <Button html-type="submit" :disabled="saveMutation.isPending.value" data-testid="publication-save">
              {{ t("common.save") }}
            </Button>
            <Button data-testid="publication-reset" @click="reset">{{ t("common.reset") }}</Button>
          </div>
          <p class="text-xs opacity-60">{{ t("common.total") }}: {{ total }}</p>
        </form>
      </section>
    </div>
  </ConfigProvider>
</template>
