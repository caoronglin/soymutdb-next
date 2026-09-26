<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, reactive, ref, toValue, watch } from "vue";
import { useRoute } from "vue-router";

import {
  createNews,
  deleteNews,
  getAdminNewsDetail,
  listAdminNews,
  restoreNews,
  updateNews,
  type NewsSummary,
} from "@soymutdb/api-client";
import { formatDate } from "@soymutdb/shared/format";
import { Button, ConfigProvider, Tag, createThemeConfig } from "@soymutdb/ui-vue";

import { t } from "../lib/i18n";
import WriteTargetNote from "../components/WriteTargetNote.vue";

/**
 * News authoring.
 *
 * News is public content, so the working state is explicit: the list shows the
 * server's `status`, a published article is deleted into the recoverable trash
 * (and restorable from the same row), and nothing is published as a side effect
 * of saving text. The body is authored as Markdown and sanitised again by the
 * portal when it renders.
 */
const queryClient = useQueryClient();
const route = useRoute();
const page = ref(1);
const statusFilter = ref<"all" | "draft" | "published" | "archived">("all");
const errorMessage = ref("");
const editingId = ref<string | null>(null);

const form = reactive({
  slug: "",
  title_en: "",
  title_zh: "",
  body_en: "",
  status: "draft" as "draft" | "published",
});

const query = useQuery({
  queryKey: computed(() => ["admin", "news", page.value, statusFilter.value]),
  queryFn: () =>
    listAdminNews({
      page: page.value,
      page_size: 20,
      status_filter: statusFilter.value === "all" ? undefined : statusFilter.value,
    }),
  staleTime: 15_000,
});

const items = computed<NewsSummary[]>(() => toValue(query.data)?.items ?? []);
const total = computed(() => toValue(query.data)?.total ?? 0);
const lastPage = computed(() => Math.max(1, Math.ceil(total.value / 20)));

function resetForm() {
  editingId.value = null;
  form.slug = "";
  form.title_en = "";
  form.title_zh = "";
  form.body_en = "";
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
      content_en: form.body_en,
      status: form.status,
    };
    return editingId.value
      ? updateNews(editingId.value, payload)
      : createNews({ ...payload, content_en: form.body_en || form.title_en });
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

/** Load one article into the editor, drafts included. */
async function loadForEdit(id: string) {
  try {
    const detail = await getAdminNewsDetail(id);
    editingId.value = id;
    form.slug = detail.slug;
    form.title_en = detail.title_en;
    form.title_zh = detail.title_zh ?? "";
    form.body_en = detail.content_en ?? "";
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
    if (status === "draft" || status === "published" || status === "archived") {
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
        <h1 class="text-xl font-semibold">{{ t("admin.news") }}</h1>

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
          </select>
        </label>

        <p v-if="query.isPending.value" class="mt-4 text-sm opacity-70">{{ t("common.loading") }}</p>
        <p v-else-if="query.isError.value" data-testid="news-error" class="mt-4 text-sm text-red-700">
          {{ t("common.errorDescription") }}
        </p>
        <p v-else-if="items.length === 0" data-testid="news-empty" class="mt-4 text-sm opacity-70">
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
                  v-if="row.status !== 'archived'"
                  type="button"
                  class="ms-3 underline text-red-700"
                  :data-testid="'news-delete-' + row.id"
                  @click="deleteMutation.mutate(row.id)"
                >
                  {{ t("common.delete") }}
                </button>
                <button
                  v-else
                  type="button"
                  class="ms-3 underline"
                  :data-testid="'news-restore-' + row.id"
                  @click="restoreMutation.mutate(row.id)"
                >
                  {{ t("common.retry") }}
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
            <input v-model="form.title_zh" class="mt-1 w-full rounded-md border bg-background px-2 py-1.5" />
          </label>
          <label class="text-sm opacity-70">
            {{ t("admin.news.form.bodyMarkdown") }}
            <textarea
              v-model="form.body_en"
              rows="8"
              class="mt-1 w-full rounded-md border bg-background p-2 font-mono text-xs"
              data-testid="news-body"
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
      </section>
    </div>
  </ConfigProvider>
</template>
