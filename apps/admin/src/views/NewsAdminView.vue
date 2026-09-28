<template>
  <div class="admin-page">
    <AdminPageHeader
      :title="t('admin.news.title')"
      :description="t('admin.news.formHelp', { defaultValue: 'Bilingual Markdown articles. Saving never publishes as a side effect.' })"
    >
      <template #actions>
        <Button size="small" data-testid="news-new" @click="resetForm">
          {{ t("admin.news.createNew") }}
        </Button>
        <span v-if="total" class="text-sm text-muted-foreground" data-testid="news-total">
          {{ t("common.total") }}: {{ total }}
        </span>
      </template>
    </AdminPageHeader>

    <div class="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
      <div class="grid content-start gap-4">
        <form class="admin-toolbar">
          <label class="admin-field">
            {{ t("common.status") }}
            <select
              v-model="statusFilter"
              class="admin-control"
              data-testid="news-status-filter"
              @change="page = 1"
            >
              <option value="all">{{ t("common.all") }}</option>
              <option value="draft">{{ t("admin.news.status.draft") }}</option>
              <option value="published">{{ t("admin.news.status.published") }}</option>
              <option value="archived">{{ t("admin.news.status.archived") }}</option>
              <option value="trash">{{ t("admin.news.trash") }}</option>
            </select>
          </label>
        </form>

        <AdminState v-if="listingPending" state="loading" testid="news-loading" :rows="6" />
        <AdminState
          v-else-if="listingError"
          state="error"
          :testid="isTrash ? 'news-trash-error' : 'news-error'"
          :title="t('common.errorDescription')"
        />

        <template v-else-if="isTrash">
          <AdminState
            v-if="deletedItems.length === 0"
            state="empty"
            testid="news-trash-empty"
            :title="t('admin.news.trashEmpty')"
          />
          <AdminCard v-else>
            <div class="admin-table-wrap">
              <table class="admin-table" data-testid="news-trash-table">
                <thead>
                  <tr>
                    <th scope="col">{{ t("news.title") }}</th>
                    <th scope="col">{{ t("admin.news.columns.deletedAt") }}</th>
                    <th scope="col">{{ t("common.actions") }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in deletedItems" :key="row.id" data-testid="news-trash-row">
                    <td>{{ row.title_en }}</td>
                    <td class="text-xs text-muted-foreground">{{ formatDate(row.deleted_at) }}</td>
                    <td>
                      <div class="admin-row-actions">
                        <button
                          type="button"
                          class="admin-link"
                          :data-testid="'news-restore-' + row.id"
                          @click="restoreMutation.mutate(String(row.id))"
                        >
                          {{ t("admin.news.restore") }}
                        </button>
                        <template v-if="purgeTargetId === String(row.id)">
                          <span class="text-xs text-destructive">
                            {{ t("admin.news.purgeConfirmTitle") }}
                          </span>
                          <button
                            type="button"
                            class="admin-link admin-link--danger"
                            :data-testid="'news-purge-confirm-' + row.id"
                            @click="purgeMutation.mutate(String(row.id))"
                          >
                            {{ t("admin.news.purge") }}
                          </button>
                          <button type="button" class="admin-link" @click="purgeTargetId = null">
                            {{ t("common.cancel") }}
                          </button>
                        </template>
                        <button
                          v-else
                          type="button"
                          class="admin-link admin-link--danger"
                          :data-testid="'news-purge-' + row.id"
                          @click="purgeTargetId = String(row.id)"
                        >
                          {{ t("admin.news.purge") }}
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </AdminCard>
        </template>

        <template v-else>
          <AdminState
            v-if="items.length === 0"
            state="empty"
            testid="news-empty"
            :title="t('common.noData')"
          />
          <AdminCard v-else>
            <div class="admin-table-wrap">
              <table class="admin-table" data-testid="news-table">
                <thead>
                  <tr>
                    <th scope="col">{{ t("news.title") }}</th>
                    <th scope="col">{{ t("common.status") }}</th>
                    <th scope="col">{{ t("common.date") }}</th>
                    <th scope="col">{{ t("common.actions") }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in items" :key="row.id" data-testid="news-row">
                    <td>{{ row.title_en }}</td>
                    <td><AdminStatusTag :status="row.status" testid="news-status" /></td>
                    <td class="text-xs text-muted-foreground">
                      {{ formatDate(row.published_at ?? row.created_at) }}
                    </td>
                    <td>
                      <div class="admin-row-actions">
                        <button
                          type="button"
                          class="admin-link"
                          :data-testid="'news-edit-' + row.id"
                          @click="loadForEdit(row.id)"
                        >
                          {{ t("common.edit") }}
                        </button>
                        <button
                          type="button"
                          class="admin-link admin-link--danger"
                          :data-testid="'news-delete-' + row.id"
                          @click="deleteMutation.mutate(row.id)"
                        >
                          {{ t("common.delete") }}
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </AdminCard>
        </template>

        <div v-if="total > 0">
          <Pager v-model="page" :last-page="lastPage" testid-prefix="news" />
        </div>
      </div>

      <AdminCard
        :title="editingId ? t('admin.news.edit') : t('admin.news.createNew')"
        testid="news-editor"
      >
        <template #actions>
          <span v-if="editingId" class="font-mono text-xs text-muted-foreground">{{ editingId }}</span>
        </template>

        <WriteTargetNote />

        <form class="mt-3 grid gap-3" @submit.prevent="saveMutation.mutate()">
          <label class="admin-field">
            {{ t("admin.news.form.slug") }}
            <input v-model="form.slug" required class="admin-control admin-control--mono" data-testid="news-slug" />
          </label>
          <label class="admin-field">
            {{ t("news.title") }} {{ t("admin.news.form.langEn") }}
            <input v-model="form.title_en" required class="admin-control" data-testid="news-title-en" />
          </label>
          <label class="admin-field">
            {{ t("news.title") }} {{ t("admin.news.form.langZh") }}
            <input v-model="form.title_zh" class="admin-control" data-testid="news-title-zh" />
          </label>
          <label class="admin-field">
            {{ t("admin.news.form.bodyMarkdown") }} {{ t("admin.news.form.langEn") }}
            <textarea v-model="form.body_en" rows="6" class="admin-control admin-control--mono" data-testid="news-body" />
          </label>
          <label class="admin-field">
            {{ t("admin.news.form.bodyMarkdown") }} {{ t("admin.news.form.langZh") }}
            <textarea v-model="form.body_zh" rows="6" class="admin-control admin-control--mono" data-testid="news-body-zh" />
          </label>
          <label class="admin-field">
            {{ t("common.status") }}
            <select v-model="form.status" class="admin-control" data-testid="news-status-select">
              <option value="draft">{{ t("admin.news.status.draft") }}</option>
              <option value="published">{{ t("admin.news.status.published") }}</option>
            </select>
          </label>

          <p
            v-if="errorMessage"
            role="alert"
            class="admin-state admin-state--error"
            data-testid="news-error-form"
          >
            {{ errorMessage }}
          </p>

          <div class="flex gap-2">
            <Button
              type="primary"
              html-type="submit"
              :disabled="saveMutation.isPending.value"
              data-testid="news-save"
            >
              {{ t("common.save") }}
            </Button>
            <Button html-type="button" data-testid="news-reset" @click="resetForm">
              {{ t("common.reset") }}
            </Button>
          </div>
        </form>

        <section class="mt-5 border-t border-border pt-3" data-testid="news-preview">
          <h3 class="admin-section-title">{{ t("admin.news.preview.renderedTitle") }}</h3>
          <div class="mt-2 grid gap-4 md:grid-cols-2">
            <div data-testid="news-preview-en">
              <p class="text-xs uppercase text-muted-foreground">{{ t("admin.news.form.langEn") }}</p>
              <div v-if="previewBodyEn" class="mt-1 text-sm" v-html="previewBodyEn" />
              <p v-else class="mt-1 text-xs text-muted-foreground">
                {{ t("admin.news.preview.empty") }}
              </p>
            </div>
            <div data-testid="news-preview-zh">
              <p class="text-xs uppercase text-muted-foreground">{{ t("admin.news.form.langZh") }}</p>
              <div v-if="previewBodyZh" class="mt-1 text-sm" v-html="previewBodyZh" />
              <p v-else class="mt-1 text-xs text-muted-foreground">
                {{ t("admin.news.preview.empty") }}
              </p>
            </div>
          </div>
        </section>
      </AdminCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, reactive, ref, toValue, watch } from "vue";
import { useRoute } from "vue-router";

import {
  createNews,
  deleteNews,
  getAdminNewsDetail,
  listAdminNews,
  listDeletedAdminNews,
  purgeNews,
  restoreNews,
  updateNews,
  type DeletedAdminNewsItem,
  type NewsSummary,
} from "@soymutdb/api-client";
import { formatDate } from "@soymutdb/shared/format";
import { Button } from "@soymutdb/ui-vue";

import AdminCard from "../components/AdminCard.vue";
import AdminPageHeader from "../components/AdminPageHeader.vue";
import AdminState from "../components/AdminState.vue";
import AdminStatusTag from "../components/AdminStatusTag.vue";
import Pager from "../components/AdminPager.vue";
import WriteTargetNote from "../components/WriteTargetNote.vue";
import { t } from "../lib/i18n";
import { renderMarkdownPreview } from "../lib/markdown-preview";

/**
 * News authoring.
 *
 * News is public content, so the working state is explicit:
 *
 * - the list shows the server's `status` (draft/published/archived);
 * - deleting a published article is a *soft delete* into the administrator's
 *   recycle bin (`GET /admin/news/deleted`), where it can be restored or
 *   permanently purged;
 * - nothing is published as a side effect of saving text.
 *
 * The body is authored as Markdown in both languages. The preview renders that
 * Markdown and sanitises it on render (see `lib/markdown-preview.ts`); the
 * portal re-sanitises the stored body again on its own render path.
 */
type NewsViewFilter = "all" | "draft" | "published" | "archived" | "trash";

const queryClient = useQueryClient();
const route = useRoute();
const page = ref(1);
const statusFilter = ref<NewsViewFilter>("all");
const errorMessage = ref("");
const editingId = ref<string | null>(null);
const purgeTargetId = ref<string | null>(null);

const isTrash = computed(() => statusFilter.value === "trash");

const form = reactive({
  slug: "",
  title_en: "",
  title_zh: "",
  body_en: "",
  body_zh: "",
  status: "draft" as "draft" | "published",
});

/** Only a real status reaches the list endpoint; trash uses its own endpoint. */
const articleStatus = computed(() =>
  statusFilter.value === "draft" ||
  statusFilter.value === "published" ||
  statusFilter.value === "archived"
    ? statusFilter.value
    : undefined,
);

const articlesQuery = useQuery({
  queryKey: computed(() => ["admin", "news", page.value, statusFilter.value]),
  queryFn: () =>
    listAdminNews({ page: page.value, page_size: 20, status_filter: articleStatus.value }),
  enabled: computed(() => !isTrash.value),
});

const trashQuery = useQuery({
  queryKey: computed(() => ["admin", "news", "deleted", page.value]),
  queryFn: () => listDeletedAdminNews({ page: page.value, page_size: 20 }),
  enabled: isTrash,
});

const items = computed<NewsSummary[]>(() => toValue(articlesQuery.data)?.items ?? []);
const deletedItems = computed<DeletedAdminNewsItem[]>(
  () => toValue(trashQuery.data)?.items ?? [],
);
const total = computed(() =>
  isTrash.value ? toValue(trashQuery.data)?.total ?? 0 : toValue(articlesQuery.data)?.total ?? 0,
);
const lastPage = computed(() => Math.max(1, Math.ceil(total.value / 20)));
const listingPending = computed(() =>
  isTrash.value ? trashQuery.isPending.value : articlesQuery.isPending.value,
);
const listingError = computed(() =>
  isTrash.value ? trashQuery.isError.value : articlesQuery.isError.value,
);

/** Sanitised Markdown for the bilingual preview panes. */
const previewBodyEn = computed(() => renderMarkdownPreview(form.body_en));
const previewBodyZh = computed(() => renderMarkdownPreview(form.body_zh));

function resetForm(): void {
  editingId.value = null;
  form.slug = "";
  form.title_en = "";
  form.title_zh = "";
  form.body_en = "";
  form.body_zh = "";
  form.status = "draft";
  errorMessage.value = "";
}

function invalidate(): void {
  void queryClient.invalidateQueries({ queryKey: ["admin", "news"] });
}

const saveMutation = useMutation({
  mutationFn: () => {
    const payload = {
      slug: form.slug.trim(),
      title_en: form.title_en.trim(),
      title_zh: form.title_zh.trim() || null,
      content_en: form.body_en || form.title_en,
      content_zh: form.body_zh || null,
      status: form.status,
    };
    return editingId.value ? updateNews(editingId.value, payload) : createNews(payload);
  },
  onSuccess: () => {
    resetForm();
    invalidate();
  },
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const deleteMutation = useMutation({
  mutationFn: (id: string) => deleteNews(id),
  onSuccess: invalidate,
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const restoreMutation = useMutation({
  mutationFn: (id: string) => restoreNews(id),
  onSuccess: invalidate,
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const purgeMutation = useMutation({
  mutationFn: (id: string) => purgeNews(id),
  onSuccess: () => {
    purgeTargetId.value = null;
    invalidate();
  },
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

/** Load one article into the editor, drafts included. */
async function loadForEdit(id: string): Promise<void> {
  try {
    const detail = await getAdminNewsDetail(id);
    editingId.value = id;
    form.slug = detail.slug;
    form.title_en = detail.title_en;
    form.title_zh = detail.title_zh ?? "";
    form.body_en = detail.content_en ?? "";
    form.body_zh = detail.content_zh ?? "";
    form.status = detail.status === "published" ? "published" : "draft";
    errorMessage.value = "";
  } catch {
    errorMessage.value = t("common.errorDescription");
  }
}

// Legacy deep links (/news/new, /news/trash, /news/:id) redirect here with a
// query. Consume it so each link restores the editor state it names.
watch(
  () => route.query,
  (query) => {
    const status = typeof query.status === "string" ? query.status : "";
    if (status === "draft" || status === "published" || status === "archived" || status === "trash") {
      statusFilter.value = status;
    }
    const edit = typeof query.edit === "string" ? query.edit : "";
    if (edit) {
      void loadForEdit(edit);
    } else if (query.new === "1") {
      resetForm();
    }
  },
  { immediate: true, deep: true },
);
</script>
