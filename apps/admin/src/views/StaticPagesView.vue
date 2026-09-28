<template>
  <div class="admin-page">
    <AdminPageHeader
      :title="t('admin.contentPages.title')"
      :description="t('admin.contentPages.subtitle')"
    />

    <div class="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
      <div class="grid content-start gap-4">
        <form class="admin-toolbar">
          <label class="admin-field">
            {{ t("common.status") }}
            <select
              v-model="statusFilter"
              class="admin-control"
              data-testid="pages-status-filter"
              @change="listPage = 1"
            >
              <option value="all">{{ t("admin.contentPages.allStatuses") }}</option>
              <option value="draft">{{ t("admin.contentPages.draft") }}</option>
              <option value="published">{{ t("admin.contentPages.published") }}</option>
              <option value="archived">{{ t("admin.contentPages.archived") }}</option>
            </select>
          </label>
          <label class="admin-field">
            {{ t("admin.contentPages.category") }}
            <input
              v-model="categoryFilter"
              class="admin-control"
              data-testid="pages-category-filter"
              @change="listPage = 1"
            />
          </label>
          <Button size="small" data-testid="pages-new" @click="resetForm">
            {{ t("admin.contentPages.newPage") }}
          </Button>
        </form>

        <AdminState v-if="listQuery.isPending.value" state="loading" testid="pages-loading" :rows="6" />
        <AdminState
          v-else-if="listQuery.isError.value"
          state="error"
          testid="pages-error"
          :title="t('common.errorDescription')"
        >
          <template #actions>
            <Button size="small" @click="listQuery.refetch()">{{ t("common.retry") }}</Button>
          </template>
        </AdminState>
        <AdminState
          v-else-if="items.length === 0"
          state="empty"
          testid="pages-empty"
          :title="t('admin.contentPages.empty')"
        />

        <AdminCard v-else>
          <div class="admin-table-wrap">
            <table class="admin-table" data-testid="pages-table">
              <thead>
                <tr>
                  <th scope="col">{{ t("admin.contentPages.title") }}</th>
                  <th scope="col">{{ t("admin.contentPages.slug") }}</th>
                  <th scope="col">{{ t("common.status") }}</th>
                  <th scope="col">{{ t("common.updated") }}</th>
                  <th scope="col">{{ t("common.actions") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in items" :key="row.id" data-testid="page-row">
                  <td>{{ row.title_en }}</td>
                  <td class="font-mono text-xs">{{ row.slug }}</td>
                  <td><AdminStatusTag :status="row.status" testid="page-status" /></td>
                  <td class="text-xs text-muted-foreground">{{ formatDate(row.updated_at) }}</td>
                  <td>
                    <div class="admin-row-actions">
                      <button
                        type="button"
                        class="admin-link"
                        :data-testid="'page-edit-' + row.id"
                        @click="loadForEdit(row.id)"
                      >
                        {{ t("common.edit") }}
                      </button>
                      <button
                        v-if="row.status !== 'published'"
                        type="button"
                        class="admin-link"
                        :data-testid="'page-publish-' + row.id"
                        @click="publishMutation.mutate(row.id)"
                      >
                        {{ t("admin.contentPages.publish") }}
                      </button>
                      <button
                        v-else
                        type="button"
                        class="admin-link"
                        :data-testid="'page-unpublish-' + row.id"
                        @click="unpublishMutation.mutate(row.id)"
                      >
                        {{ t("admin.contentPages.unpublish") }}
                      </button>
                      <button
                        type="button"
                        class="admin-link admin-link--danger"
                        :data-testid="'page-delete-' + row.id"
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

          <template #footer>
            <Pager v-model="listPage" :last-page="lastPage" testid-prefix="pages" />
          </template>
        </AdminCard>
      </div>

      <AdminCard
        :title="editingId ? t('admin.contentPages.editPage') : t('admin.contentPages.createPage')"
        testid="page-editor"
      >
        <template #actions>
          <span v-if="editingId" class="font-mono text-xs text-muted-foreground">{{ editingId }}</span>
        </template>

        <WriteTargetNote />

        <form class="mt-3 grid gap-3" @submit.prevent="saveMutation.mutate()">
          <label class="admin-field">
            {{ t("admin.contentPages.slug") }}
            <input
              v-model="form.slug"
              required
              :disabled="Boolean(editingId)"
              class="admin-control admin-control--mono"
              data-testid="page-slug"
            />
          </label>
          <label class="admin-field">
            {{ t("admin.contentPages.titleEn") }}
            <input v-model="form.title_en" required class="admin-control" data-testid="page-title-en" />
          </label>
          <label class="admin-field">
            {{ t("admin.contentPages.titleZh") }}
            <input v-model="form.title_zh" class="admin-control" data-testid="page-title-zh" />
          </label>
          <label class="admin-field">
            {{ t("admin.contentPages.summary") }}
            <textarea v-model="form.summary" rows="2" class="admin-control" data-testid="page-summary" />
          </label>
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="admin-field">
              {{ t("admin.contentPages.category") }}
              <input v-model="form.category" class="admin-control" data-testid="page-category" />
            </label>
            <label class="admin-field">
              {{ t("admin.contentPages.sortOrder") }}
              <input
                v-model.number="form.sort_order"
                type="number"
                min="0"
                class="admin-control"
                data-testid="page-sort-order"
              />
            </label>
          </div>
          <label class="admin-field">
            {{ t("admin.contentPages.contentEn") }}
            <textarea
              v-model="form.content_en"
              rows="6"
              class="admin-control admin-control--mono"
              data-testid="page-content-en"
            />
          </label>
          <label class="flex items-center gap-2 text-sm">
            <input
              v-model="form.content_zh_enabled"
              type="checkbox"
              data-testid="page-content-zh-enabled"
            />
            {{ t("admin.contentPages.contentZh") }}
          </label>
          <textarea
            v-if="form.content_zh_enabled"
            v-model="form.content_zh"
            rows="6"
            class="admin-control admin-control--mono"
            data-testid="page-content-zh"
          />
          <label v-if="!editingId" class="admin-field">
            {{ t("common.status") }}
            <select v-model="form.status" class="admin-control" data-testid="page-status-select">
              <option value="draft">{{ t("admin.contentPages.draft") }}</option>
              <option value="published">{{ t("admin.contentPages.published") }}</option>
              <option value="archived">{{ t("admin.contentPages.archived") }}</option>
            </select>
          </label>

          <p
            v-if="errorMessage"
            role="alert"
            class="admin-state admin-state--error"
            data-testid="page-save-error"
          >
            {{ errorMessage }}
          </p>
          <p v-if="savedMessage" role="status" class="admin-state" data-testid="page-saved">
            {{ savedMessage }}
          </p>

          <div class="flex gap-2">
            <Button
              type="primary"
              html-type="submit"
              :disabled="saveMutation.isPending.value"
              data-testid="page-save"
            >
              {{ t("common.save") }}
            </Button>
            <Button html-type="button" data-testid="page-reset" @click="resetForm">
              {{ t("common.reset") }}
            </Button>
          </div>
        </form>

        <div v-if="editingId" class="mt-5 border-t border-border pt-3" data-testid="page-version-history">
          <h3 class="admin-section-title">{{ t("admin.contentPages.versions") }}</h3>
          <AdminState v-if="versionsQuery.isPending.value" state="loading" :rows="2" class="mt-2" />
          <AdminState
            v-else-if="versionsQuery.isError.value"
            state="error"
            testid="page-versions-error"
            class="mt-2"
            :title="t('common.errorDescription')"
          />
          <AdminState
            v-else-if="versions.length === 0"
            state="empty"
            testid="page-versions-empty"
            class="mt-2"
            :title="t('common.noData')"
          />
          <ul v-else class="mt-2 grid gap-1 text-xs">
            <li
              v-for="version in versions"
              :key="version.id"
              class="flex items-center justify-between gap-2"
              data-testid="page-version"
            >
              <span>v{{ version.version }} · {{ formatDate(version.created_at) }}</span>
              <button
                type="button"
                class="admin-link"
                :data-testid="'page-restore-' + version.version"
                @click="restoreMutation.mutate(version.version)"
              >
                {{ t("admin.contentPages.restore") }}
              </button>
            </li>
          </ul>
        </div>
      </AdminCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, reactive, ref, toValue, watch } from "vue";
import { useRoute } from "vue-router";

import {
  createStaticPage,
  deleteStaticPage,
  getStaticPage,
  listStaticPageVersions,
  listStaticPages,
  publishStaticPage,
  restoreStaticPageVersion,
  unpublishStaticPage,
  updateStaticPage,
  type ContentVersion,
  type StaticPage,
  type StaticPageStatus,
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

/**
 * Static-page content management.
 *
 * The list is the server's, drafts included, and the editor is a form over the
 * typed admin-content client. Publish/unpublish are explicit, separate actions:
 * saving text never changes visibility as a side effect, which is what makes the
 * status column mean what it says.
 *
 * The panel also surfaces the server-owned content version history, because a
 * page is the one admin surface where a bad save has no other recovery path.
 */
const queryClient = useQueryClient();
const route = useRoute();
const listPage = ref(1);
const statusFilter = ref<"all" | StaticPageStatus>("all");
const categoryFilter = ref("");
const editingId = ref<string | null>(null);
const errorMessage = ref("");
const savedMessage = ref("");

const form = reactive({
  slug: "",
  title_en: "",
  title_zh: "",
  summary: "",
  category: "",
  sort_order: 0,
  content_en: "",
  content_zh: "",
  content_zh_enabled: false,
  status: "draft" as StaticPageStatus,
  edit_comment: "",
});

const listQuery = useQuery({
  queryKey: computed(() => [
    "admin",
    "content",
    "pages",
    listPage.value,
    statusFilter.value,
    categoryFilter.value,
  ]),
  queryFn: () =>
    listStaticPages({
      page: listPage.value,
      page_size: 20,
      status: statusFilter.value === "all" ? undefined : statusFilter.value,
      category: categoryFilter.value.trim() || undefined,
    }),
});

const items = computed<StaticPage[]>(() => toValue(listQuery.data)?.items ?? []);
const total = computed(() => toValue(listQuery.data)?.total ?? 0);
const lastPage = computed(() => Math.max(1, Math.ceil(total.value / 20)));

const versionsQuery = useQuery({
  queryKey: computed(() => ["admin", "content", "versions", editingId.value]),
  queryFn: () => listStaticPageVersions(editingId.value as string),
  enabled: computed(() => Boolean(editingId.value)),
});

const versions = computed<ContentVersion[]>(() => toValue(versionsQuery.data) ?? []);

function resetForm(): void {
  editingId.value = null;
  form.slug = "";
  form.title_en = "";
  form.title_zh = "";
  form.summary = "";
  form.category = "";
  form.sort_order = 0;
  form.content_en = "";
  form.content_zh = "";
  form.content_zh_enabled = false;
  form.status = "draft";
  form.edit_comment = "";
  errorMessage.value = "";
  savedMessage.value = "";
}

function applyDetail(detail: StaticPage): void {
  editingId.value = detail.id;
  form.slug = detail.slug;
  form.title_en = detail.title_en;
  form.title_zh = detail.title_zh ?? "";
  form.summary = detail.summary ?? "";
  form.category = detail.category ?? "";
  form.sort_order = detail.sort_order;
  form.content_en = detail.content_en;
  form.content_zh = detail.content_zh ?? "";
  form.content_zh_enabled = detail.content_zh !== null;
  form.status = detail.status;
}

const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin", "content"] });

const saveMutation = useMutation({
  mutationFn: () => {
    const shared = {
      title_en: form.title_en.trim(),
      title_zh: form.title_zh.trim() || null,
      content_en: form.content_en || form.title_en.trim(),
      content_zh: form.content_zh_enabled ? form.content_zh : null,
      summary: form.summary.trim() || null,
      category: form.category.trim() || null,
      sort_order: Number(form.sort_order) || 0,
      edit_comment: form.edit_comment.trim() || null,
    };
    return editingId.value
      ? updateStaticPage(editingId.value, shared)
      : createStaticPage({
          slug: form.slug.trim(),
          status: form.status,
          ...shared,
        });
  },
  onSuccess: (detail) => {
    applyDetail(detail);
    savedMessage.value = t("common.success");
    errorMessage.value = "";
    void invalidate();
  },
  onError: () => {
    savedMessage.value = "";
    errorMessage.value = t("common.errorDescription");
  },
});

const publishMutation = useMutation({
  mutationFn: (id: string) => publishStaticPage(id),
  onSuccess: () => void invalidate(),
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const unpublishMutation = useMutation({
  mutationFn: (id: string) => unpublishStaticPage(id),
  onSuccess: () => void invalidate(),
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const deleteMutation = useMutation({
  mutationFn: (id: string) => deleteStaticPage(id),
  onSuccess: () => void invalidate(),
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

const restoreMutation = useMutation({
  mutationFn: (version: number) => restoreStaticPageVersion(editingId.value as string, version),
  onSuccess: (detail) => {
    applyDetail(detail);
    void invalidate();
  },
  onError: () => {
    errorMessage.value = t("common.errorDescription");
  },
});

/** Load one page, drafts included, into the editor. */
async function loadForEdit(id: string): Promise<void> {
  try {
    const detail = await getStaticPage(id);
    applyDetail(detail);
    errorMessage.value = "";
    savedMessage.value = "";
  } catch {
    errorMessage.value = t("common.errorDescription");
  }
}

// Legacy deep links (/content/pages and the retired /content/pages deep links)
// redirect here with a query; consume it so each link restores the state it
// names.
watch(
  () => route.query,
  (query) => {
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
