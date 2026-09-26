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
import { Button, ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";
import { renderMarkdownPreview } from "../lib/markdown-preview";
import WriteTargetNote from "../components/WriteTargetNote.vue";

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
    listAdminNews({
      page: page.value,
      page_size: 20,
      status_filter: articleStatus.value,
    }),
  enabled: computed(() => !isTrash.value),
  staleTime: 15_000,
});

const trashQuery = useQuery({
  queryKey: computed(() => ["admin", "news", "deleted", page.value]),
  queryFn: () => listDeletedAdminNews({ page: page.value, page_size: 20 }),
  enabled: isTrash,
  staleTime: 15_000,
});

const items = computed<NewsSummary[]>(() => toValue(articlesQuery.data)?.items ?? []);
const deletedItems = computed<DeletedAdminNewsItem[]>(() => toValue(trashQuery.data)?.items ?? []);
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

function resetForm() {
  editingId.value = null;
  form.slug = "";
  form.title_en = "";
  form.title_zh = "";
  form.body_en = "";
  form.body_zh = "";
  form.status = "draft";
  errorMessage.value = "";
}

const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin", "news"] });

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
    void invalidate();
  },
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const deleteMutation = useMutation({
  mutationFn: (id: string) => deleteNews(id),
  onSuccess: () => void invalidate(),
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const restoreMutation = useMutation({
  mutationFn: (id: string) => restoreNews(id),
  onSuccess: () => void invalidate(),
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const purgeMutation = useMutation({
  mutationFn: (id: string) => purgeNews(id),
  onSuccess: () => {
    purgeTargetId.value = null;
    void invalidate();
  },
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

/** Load one article into the editor, drafts included. */
async function loadForEdit(id: string) {
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
    if (
      status === "draft" ||
      status === "published" ||
      status === "archived" ||
      status === "trash"
    ) {
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

<template>
  <ConfigProvider :theme="createThemeConfig({ dark: false })">
    <div class="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
      <section>
        <h1 class="text-xl font-semibold">{{ t("admin.news.title") }}</h1>

        <label class="mt-4 inline-block text-sm opacity-70">
          {{ t("common.status") }}
          <select
            v-model="statusFilter"
            class="ms-2 rounded-md border bg-background px-2 py-1.5"
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

        <p v-if="listingPending" class="mt-4 text-sm opacity-70">{{ t("common.loading") }}</p>
        <p
          v-else-if="listingError"
          :data-testid="isTrash ? 'news-trash-error' : 'news-error'"
          class="mt-4 text-sm text-red-700"
        >
          {{ t("common.errorDescription") }}
        </p>

        <template v-else-if="isTrash">
          <p v-if="deletedItems.length === 0" data-testid="news-trash-empty" class="mt-4 text-sm opacity-70">
            {{ t("admin.news.trashEmpty") }}
          </p>
          <table v-else class="mt-4 w-full text-sm" data-testid="news-trash-table">
            <thead class="text-left opacity-60">
              <tr>
                <th scope="col" class="py-2">{{ t("news.title") }}</th>
                <th scope="col" class="py-2">{{ t("admin.news.columns.deletedAt") }}</th>
                <th scope="col" class="py-2">{{ t("common.actions") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in deletedItems"
                :key="row.id"
                class="border-t"
                data-testid="news-trash-row"
              >
                <td class="py-2">{{ row.title_en }}</td>
                <td class="py-2 text-xs opacity-70">{{ formatDate(row.deleted_at) }}</td>
                <td class="py-2">
                  <button
                    type="button"
                    class="underline"
                    :data-testid="'news-restore-' + row.id"
                    @click="restoreMutation.mutate(String(row.id))"
                  >
                    {{ t("admin.news.restore") }}
                  </button>
                  <template v-if="purgeTargetId === String(row.id)">
                    <span class="ms-3 text-xs text-red-700">
                      {{ t("admin.news.purgeConfirmTitle") }}
                    </span>
                    <button
                      type="button"
                      class="ms-2 underline text-red-700"
                      :data-testid="'news-purge-confirm-' + row.id"
                      @click="purgeMutation.mutate(String(row.id))"
                    >
                      {{ t("admin.news.purge") }}
                    </button>
                    <button
                      type="button"
                      class="ms-2 underline"
                      @click="purgeTargetId = null"
                    >
                      {{ t("common.cancel") }}
                    </button>
                  </template>
                  <button
                    v-else
                    type="button"
                    class="ms-3 underline text-red-700"
                    :data-testid="'news-purge-' + row.id"
                    @click="purgeTargetId = String(row.id)"
                  >
                    {{ t("admin.news.purge") }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </template>

        <template v-else>
          <p v-if="items.length === 0" data-testid="news-empty" class="mt-4 text-sm opacity-70">
            {{ t("common.noData") }}
          </p>
          <table v-else class="mt-4 w-full text-sm" data-testid="news-table">
            <thead class="text-left opacity-60">
              <tr>
                <th scope="col" class="py-2">{{ t("news.title") }}</th>
                <th scope="col" class="py-2">{{ t("common.status") }}</th>
                <th scope="col" class="py-2">{{ t("common.date") }}</th>
                <th scope="col" class="py-2">{{ t("common.actions") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in items" :key="row.id" class="border-t" data-testid="news-row">
                <td class="py-2">{{ row.title_en }}</td>
                <td class="py-2">
                  <Tag :color="row.status === 'published' ? 'green' : 'default'" data-testid="news-status">
                    {{ row.status }}
                  </Tag>
                </td>
                <td class="py-2 text-xs opacity-70">{{ formatDate(row.published_at ?? row.created_at) }}</td>
                <td class="py-2">
                  <button
                    type="button"
                    class="underline"
                    :data-testid="'news-edit-' + row.id"
                    @click="loadForEdit(row.id)"
                  >
                    {{ t("common.edit") }}
                  </button>
                  <button
                    type="button"
                    class="ms-3 underline text-red-700"
                    :data-testid="'news-delete-' + row.id"
                    @click="deleteMutation.mutate(row.id)"
                  >
                    {{ t("common.delete") }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </template>

        <nav v-if="total > 0" class="mt-4 flex items-center gap-3" :aria-label="t('common.pagination')">
          <button
            type="button"
            class="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            :disabled="page <= 1"
            @click="page -= 1"
          >
            {{ t("common.previous") }}
          </button>
          <span class="text-sm opacity-70" data-testid="news-page">{{ page }} / {{ lastPage }}</span>
          <button
            type="button"
            class="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            :disabled="page >= lastPage"
            @click="page += 1"
          >
            {{ t("common.next") }}
          </button>
        </nav>
      </section>

      <section class="rounded-lg border p-4">
        <h2 class="text-sm font-medium">
          {{ editingId ? t("common.edit") : t("common.save") }}
          <span v-if="editingId" class="ms-2 font-mono text-xs opacity-70">{{ editingId }}</span>
        </h2>
        <WriteTargetNote />
        <form class="mt-3 grid gap-3" @submit.prevent="saveMutation.mutate()">
          <label class="text-sm opacity-70">
            {{ t("admin.news.form.slug") }}
            <input
              v-model="form.slug"
              required
              class="mt-1 w-full rounded-md border bg-background px-2 py-1.5 font-mono text-xs"
              data-testid="news-slug"
            />
          </label>
          <label class="text-sm opacity-70">
            {{ t("news.title") }} {{ t("admin.news.form.langEn") }}
            <input
              v-model="form.title_en"
              required
              class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
              data-testid="news-title-en"
            />
          </label>
          <label class="text-sm opacity-70">
            {{ t("news.title") }} {{ t("admin.news.form.langZh") }}
            <input
              v-model="form.title_zh"
              class="mt-1 w-full rounded-md border bg-background px-2 py-1.5"
              data-testid="news-title-zh"
            />
          </label>
          <label class="text-sm opacity-70">
            {{ t("admin.news.form.bodyMarkdown") }} {{ t("admin.news.form.langEn") }}
            <textarea
              v-model="form.body_en"
              rows="6"
              class="mt-1 w-full rounded-md border bg-background p-2 font-mono text-xs"
              data-testid="news-body"
            />
          </label>
          <label class="text-sm opacity-70">
            {{ t("admin.news.form.bodyMarkdown") }} {{ t("admin.news.form.langZh") }}
            <textarea
              v-model="form.body_zh"
              rows="6"
              class="mt-1 w-full rounded-md border bg-background p-2 font-mono text-xs"
              data-testid="news-body-zh"
            />
          </label>
          <label class="text-sm opacity-70">
            {{ t("common.status") }}
            <select v-model="form.status" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" data-testid="news-status-select">
              <option value="draft">{{ t("admin.news.status.draft") }}</option>
              <option value="published">{{ t("admin.news.status.published") }}</option>
            </select>
          </label>
          <p v-if="errorMessage" role="alert" class="text-sm text-red-700" data-testid="news-error-form">
            {{ errorMessage }}
          </p>
          <div class="flex gap-2">
            <Button html-type="submit" :disabled="saveMutation.isPending.value" data-testid="news-save">
              {{ t("common.save") }}
            </Button>
            <Button data-testid="news-reset" @click="resetForm">{{ t("common.reset") }}</Button>
          </div>
          <p class="text-xs opacity-60">{{ t("common.total") }}: {{ total }}</p>
        </form>

        <section class="mt-4 rounded-md border p-3" data-testid="news-preview">
          <h3 class="text-sm font-medium">{{ t("admin.news.preview.renderedTitle") }}</h3>
          <div class="mt-2 grid gap-4 md:grid-cols-2">
            <div data-testid="news-preview-en">
              <p class="text-xs uppercase opacity-60">{{ t("admin.news.form.langEn") }}</p>
              <div v-if="previewBodyEn" class="mt-1 text-sm" v-html="previewBodyEn" />
              <p v-else class="mt-1 text-xs opacity-60">{{ t("admin.news.preview.empty") }}</p>
            </div>
            <div data-testid="news-preview-zh">
              <p class="text-xs uppercase opacity-60">{{ t("admin.news.form.langZh") }}</p>
              <div v-if="previewBodyZh" class="mt-1 text-sm" v-html="previewBodyZh" />
              <p v-else class="mt-1 text-xs opacity-60">{{ t("admin.news.preview.empty") }}</p>
            </div>
          </div>
        </section>
      </section>
    </div>
  </ConfigProvider>
</template>
