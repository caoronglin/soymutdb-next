<template>
  <div class="admin-page">
    <AdminPageHeader :title="t('publications.title')" :description="t('admin.publications.subtitle', { defaultValue: 'Peer-reviewed references attached to this database.' })">
      <template #actions>
        <Button size="small" data-testid="publications-new" @click="reset">
          {{ t("common.reset") }}
        </Button>
      </template>
    </AdminPageHeader>

    <div class="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
      <div class="grid content-start gap-4">
        <form class="admin-toolbar" role="search" @submit.prevent="page = 1">
          <label class="admin-field flex-1">
            {{ t("common.search") }}
            <input
              v-model="search"
              class="admin-control"
              :placeholder="t('common.search')"
              data-testid="publications-search"
            />
          </label>
          <Button html-type="submit" size="small">{{ t("common.apply") }}</Button>
        </form>

        <AdminState v-if="query.isPending.value" state="loading" testid="publications-loading" />
        <AdminState
          v-else-if="query.isError.value"
          state="error"
          testid="publications-error"
          :title="t('common.errorDescription')"
        >
          <template #actions>
            <Button size="small" @click="query.refetch()">{{ t("common.retry") }}</Button>
          </template>
        </AdminState>
        <AdminState
          v-else-if="items.length === 0"
          state="empty"
          testid="publications-empty"
          :title="t('publications.noPublications')"
        />

        <AdminCard v-else>
          <div class="admin-table-wrap">
            <table class="admin-table" data-testid="publications-table">
              <thead>
                <tr>
                  <th scope="col">{{ t("publications.title") }}</th>
                  <th scope="col">{{ t("publications.year") }}</th>
                  <th scope="col">{{ t("common.actions") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in items" :key="row.id" data-testid="publication-row">
                  <td>
                    {{ row.title }}
                    <AdminStatusTag v-if="row.is_featured" status="default" />
                    <p class="mt-0.5 text-xs text-muted-foreground">{{ row.authors }}</p>
                  </td>
                  <td class="text-xs text-muted-foreground">{{ row.year ?? "—" }}</td>
                  <td>
                    <div class="admin-row-actions">
                      <button
                        type="button"
                        class="admin-link"
                        :data-testid="'publication-edit-' + row.id"
                        @click="edit(row)"
                      >
                        {{ t("common.edit") }}
                      </button>
                      <button
                        type="button"
                        class="admin-link admin-link--danger"
                        :data-testid="'publication-delete-' + row.id"
                        @click="pendingDelete = row"
                      >
                        {{ t("common.delete") }}
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <template #footer>
            <Pager v-model="page" :last-page="lastPage" testid-prefix="publications" />
          </template>
        </AdminCard>
      </div>

      <AdminCard
        :title="form.id ? t('common.edit') : t('admin.publications.new', { defaultValue: 'New publication' })"
        testid="publication-editor"
      >
        <form class="grid gap-3" @submit.prevent="saveMutation.mutate()">
          <label class="admin-field">
            {{ t("publications.title") }}
            <input v-model="form.title" required class="admin-control" data-testid="publication-title" />
          </label>
          <label class="admin-field">
            {{ t("publications.authors") }}
            <input v-model="form.authors" required class="admin-control" data-testid="publication-authors" />
          </label>
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="admin-field">
              {{ t("publications.journal") }}
              <input v-model="form.journal" class="admin-control" data-testid="publication-journal" />
            </label>
            <label class="admin-field">
              {{ t("publications.year") }}
              <input
                v-model="form.year"
                class="admin-control"
                inputmode="numeric"
                data-testid="publication-year"
              />
            </label>
          </div>
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="admin-field">
              {{ t("publications.doi") }}
              <input v-model="form.doi" class="admin-control admin-control--mono" data-testid="publication-doi" />
            </label>
            <label class="admin-field">
              {{ t("admin.publications.pmid", { defaultValue: "PMID" }) }}
              <input v-model="form.pmid" class="admin-control admin-control--mono" data-testid="publication-pmid" />
            </label>
          </div>
          <label class="admin-field">
            {{ t("admin.publications.abstract", { defaultValue: "Abstract" }) }}
            <textarea v-model="form.abstract" rows="4" class="admin-control" data-testid="publication-abstract" />
          </label>
          <label class="flex items-center gap-2 text-sm">
            <input v-model="form.is_featured" type="checkbox" data-testid="publication-featured" />
            {{ t("admin.publications.featured") }}
          </label>

          <p
            v-if="errorMessage"
            role="alert"
            class="admin-state admin-state--error"
            data-testid="publication-error"
          >
            {{ errorMessage }}
          </p>

          <div class="flex gap-2">
            <Button
              type="primary"
              html-type="submit"
              :disabled="saveMutation.isPending.value"
              data-testid="publication-save"
            >
              {{ t("common.save") }}
            </Button>
            <Button html-type="button" data-testid="publication-reset" @click="reset">
              {{ t("common.reset") }}
            </Button>
          </div>
        </form>
      </AdminCard>
    </div>

    <!-- Delete is a dialog, not an inline strip: the row is cited by DOI
         elsewhere, so the confirmation has to be the operator's focus. -->
    <div
      v-if="pendingDelete"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4"
      data-testid="publication-delete-confirm"
      @mousedown.self="pendingDelete = null"
    >
      <div role="alertdialog" aria-labelledby="publication-delete-heading" class="w-full max-w-md rounded-xl border border-border bg-popover p-4 shadow-2xl">
        <h2 id="publication-delete-heading" class="admin-section-title">
          {{ t("admin.publications.deleteTitle", { defaultValue: "Delete publication" }) }}
        </h2>
        <p class="mt-2 text-sm">
          {{ pendingDelete.title }}
          <span v-if="pendingDelete.doi" class="ms-1 font-mono text-xs">DOI {{ pendingDelete.doi }}</span>
        </p>
        <div class="mt-4 flex gap-2">
          <Button
            danger
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
    </div>
  </div>
</template>

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
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
import Pager from "../components/AdminPager.vue";
import { t } from "../lib/i18n";

/**
 * Publications CRUD.
 *
 * Delete states what will be removed: the row is cited by DOI elsewhere, so an
 * accidental delete is not "just a row". A create or update failure leaves the
 * form values in place so the operator does not retype the abstract to retry.
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
  queryFn: () =>
    listAdminPublications({ page: page.value, page_size: 20, search: search.value || undefined }),
});

const items = computed(() => toValue(query.data)?.items ?? []);
const total = computed(() => toValue(query.data)?.total ?? 0);
const lastPage = computed(() => Math.max(1, Math.ceil(total.value / 20)));

function edit(row: Publication): void {
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
  errorMessage.value = "";
}

function reset(): void {
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
