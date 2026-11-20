import { CloseOutlined, DeleteOutlined, EditOutlined, FileTextOutlined, HistoryOutlined, PlusOutlined, SendOutlined } from "@ant-design/icons";
import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { http } from "@soymutdb/api-client";
import { Skeleton, Alert, Badge, Button, Input, ProCard, Select, Typography } from "@/lib/antd";
import { ConfirmDialog } from "../../components/confirm-dialog";
import { DataTable, type DataTableColumn } from "../../components/data-table";
import { contentKeys } from "./query-keys";
import { StaticPageMigrationReport } from "./static-page-migration-report";
import { parseContentPageSearch, serializeContentPageSearch } from "./search";

export type PageStatus = "draft" | "published" | "archived";

export interface StaticPage {
  id: string; slug: string; title_en: string; title_zh: string | null; content_en: string; content_zh: string | null; summary: string | null; category: string | null; status: PageStatus; sort_order: number; author_name: string | null; published_at: string | null; current_version: number; created_at: string; updated_at: string;
}
export interface StaticPageCreate { slug: string; title_en: string; title_zh?: string; content_en: string; content_zh?: string; summary?: string; category?: string; sort_order?: number; status?: PageStatus; edit_comment?: string; }
export interface StaticPageUpdate { title_en?: string; title_zh?: string; content_en?: string; content_zh?: string; summary?: string; category?: string; sort_order?: number; edit_comment?: string; }
export interface PageFormValues { slug: string; title_en: string; title_zh: string; content_en: string; content_zh: string; summary: string; category: string; sort_order: string; status: PageStatus; edit_comment: string; }
interface PageListResponse { items: StaticPage[]; total: number; }

export interface PageFormDialogProps { editing: StaticPage | null; open: boolean; onOpenChange: (open: boolean) => void; onSubmit: (values: PageFormValues) => void; loading: boolean; error: unknown; }
export interface VersionHistoryDialogProps { page: StaticPage; open: boolean; onOpenChange: (open: boolean) => void; }
export interface VersionDetailProps { version: { id: string; page_id: string; version: number; title_en: string; title_zh: string | null; content_en: string; content_zh: string | null; summary: string | null; edited_by: string | null; edit_comment: string | null; created_at: string }; onBack: () => void; }
export interface PagesTabProps { PageFormDialog: React.ComponentType<PageFormDialogProps>; VersionHistoryDialog: React.ComponentType<VersionHistoryDialogProps & { VersionDetail: React.ComponentType<VersionDetailProps> }>; VersionDetail: React.ComponentType<VersionDetailProps>; }

function statusBadgeVariant(status: PageStatus): "warning" | "success" | "secondary" {
  if (status === "published") return "success";
  if (status === "draft") return "warning";
  return "secondary";
}

export function PagesTab({ PageFormDialog, VersionHistoryDialog, VersionDetail }: PagesTabProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const rawSearch = useSearch({ strict: false }) as Record<string, unknown>;
  const search = parseContentPageSearch(rawSearch);
  const { page, status: statusFilter, category: categoryFilter } = search;
  const updateSearch = (next: typeof search) =>
    navigate({
      search: (() => serializeContentPageSearch(next)) as never,
      replace: true,
    });
  const clearEditRoute = () => {
    if (search.edit) updateSearch({ ...search, edit: undefined });
  };
  const setPage = (nextPage: number) => updateSearch({ ...search, page: nextPage });
  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<StaticPage | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<StaticPage | null>(null);
  const [publishTarget, setPublishTarget] = React.useState<{
    page: StaticPage;
    action: "publish" | "unpublish";
  } | null>(null);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [publishError, setPublishError] = React.useState<string | null>(null);
  const [versionsTarget, setVersionsTarget] = React.useState<StaticPage | null>(
    null,
  );
  const openedEditId = React.useRef<string | undefined>(undefined);

  const { data, isLoading, isError, isFetching } = useQuery<PageListResponse>({
    queryKey: contentKeys.pages({ page, status: statusFilter, category: categoryFilter }),
    queryFn: () =>
      http.get<PageListResponse>("/admin/content/pages", {
        params: {
          page,
          page_size: 20,
          status: statusFilter !== "all" ? statusFilter : undefined,
          category: categoryFilter || undefined,
        },
      }),
  });
  const requestedEditQuery = useQuery<StaticPage>({
    queryKey: ["admin", "content-page", search.edit],
    queryFn: () => http.get<StaticPage>(`/admin/content/pages/${encodeURIComponent(search.edit!)}`),
    enabled: Boolean(search.edit),
    retry: false,
  });

  const createMutation = useMutation({
    mutationFn: (payload: StaticPageCreate) =>
      http.post("/admin/content/pages", { json: payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: contentKeys.all });
      setFormOpen(false);
      setEditing(null);
      openedEditId.current = search.edit;
      clearEditRoute();
    },
  });

  const updateMutation = useMutation({
    mutationFn: (params: { id: string; payload: StaticPageUpdate }) =>
      http.put(`/admin/content/pages/${params.id}`, { json: params.payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: contentKeys.all });
      setFormOpen(false);
      setEditing(null);
      openedEditId.current = search.edit;
      clearEditRoute();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => http.delete(`/admin/content/pages/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: contentKeys.all });
      setDeleteTarget(null);
      setDeleteError(null);
    },
    onError: (error) => {
      // The dialog stays open on a rejected delete and explains the refusal
      // inside it; a silent failure looked exactly like a successful delete.
      setDeleteError(error instanceof Error ? error.message : String(error));
    },
  });

  const publishMutation = useMutation({
    mutationFn: (id: string) =>
      http.post(`/admin/content/pages/${id}/publish`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: contentKeys.all });
      setPublishTarget(null);
      setPublishError(null);
    },
    onError: (error) => {
      setPublishError(error instanceof Error ? error.message : String(error));
    },
  });

  const unpublishMutation = useMutation({
    mutationFn: (id: string) =>
      http.post(`/admin/content/pages/${id}/unpublish`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: contentKeys.all });
      setPublishTarget(null);
      setPublishError(null);
    },
    onError: (error) => {
      setPublishError(error instanceof Error ? error.message : String(error));
    },
  });

  const openCreate = () => {
    createMutation.reset();
    updateMutation.reset();
    openedEditId.current = search.edit;
    clearEditRoute();
    setEditing(null);
    setFormOpen(true);
  };

  const openEdit = (p: StaticPage) => {
    createMutation.reset();
    updateMutation.reset();
    openedEditId.current = p.id;
    updateSearch({ ...search, edit: p.id });
    setEditing(p);
    setFormOpen(true);
  };

  React.useEffect(() => {
    const requestedId = search.edit;
    if (!requestedId) {
      openedEditId.current = undefined;
      return;
    }
    const page = requestedEditQuery.data;
    if (!page || page.id !== requestedId || openedEditId.current === requestedId) return;
    openedEditId.current = requestedId;
    createMutation.reset();
    updateMutation.reset();
    setEditing(page);
    setFormOpen(true);
    // The two mutations are stable objects from useMutation; they are reset to
    // clear a previous error state and must not retrigger this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.edit, requestedEditQuery.data]);

  const handleSubmit = (values: PageFormValues) => {
    if (editing) {
      const payload: StaticPageUpdate = {
        title_en: values.title_en,
        title_zh: values.title_zh || undefined,
        content_en: values.content_en,
        content_zh: values.content_zh || undefined,
        summary: values.summary || undefined,
        category: values.category || undefined,
        sort_order: Number(values.sort_order) || 0,
        edit_comment: values.edit_comment || undefined,
      };
      updateMutation.mutate({ id: editing.id, payload });
    } else {
      const payload: StaticPageCreate = {
        slug: values.slug,
        title_en: values.title_en,
        title_zh: values.title_zh || undefined,
        content_en: values.content_en,
        content_zh: values.content_zh || undefined,
        summary: values.summary || undefined,
        category: values.category || undefined,
        sort_order: Number(values.sort_order) || 0,
        status: values.status,
        edit_comment: values.edit_comment || undefined,
      };
      createMutation.mutate(payload);
    }
  };

  const pages = data?.items ?? [];
  const formLoading = createMutation.isPending || updateMutation.isPending;
  const formError = editing ? updateMutation.error : createMutation.error;
  const totalCount = data?.total ?? 0;
  // Browser-gate contract for GET /admin/content/pages: "loading" while the
  // request is in flight, then "ready" (rows or the empty state) or "error".
  const pageListState = isError ? "error" : isFetching ? "loading" : "ready";

  const columns: DataTableColumn<StaticPage>[] = [
    {
      key: "title",
      header: t("admin.content.colTitle", { defaultValue: "Title" }),
      sortable: true,
      sortAccessor: (p) => p.title_en,
      cell: (p) => (
        <div className="min-w-0">
          <p className="font-medium">{p.title_en}</p>
          {p.title_zh ? (
            <p className="truncate text-xs text-muted-foreground">
              {p.title_zh}
            </p>
          ) : null}
        </div>
      ),
    },
    {
      key: "slug",
      header: t("admin.content.colSlug", { defaultValue: "Slug" }),
      sortable: true,
      sortAccessor: (p) => p.slug,
      cell: (p) => (
        <span className="font-mono text-xs text-muted-foreground">
          /{p.slug}
        </span>
      ),
    },
    {
      key: "category",
      header: t("admin.content.colCategory", { defaultValue: "Category" }),
      sortable: true,
      sortAccessor: (p) => p.category ?? "",
      cell: (p) => <span className="text-sm">{p.category ?? "—"}</span>,
    },
    {
      key: "status",
      header: t("admin.content.colStatus", { defaultValue: "Status" }),
      sortable: true,
      sortAccessor: (p) => p.status,
      cell: (p) => (
        <Badge color={statusBadgeVariant(p.status)}>{t(`admin.content.status.${p.status}`, { defaultValue: p.status })}</Badge>
      ),
    },
    {
      key: "updated_at",
      header: t("admin.content.colUpdated", { defaultValue: "Updated" }),
      sortable: true,
      sortAccessor: (p) => p.updated_at,
      cell: (p) => (
        <span className="text-sm text-muted-foreground">{p.updated_at}</span>
      ),
    },
    {
      key: "actions",
      header: t("admin.content.colActions", { defaultValue: "Actions" }),
      align: "right",
      cell: (p) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => openEdit(p)}
            title={t("admin.content.edit", { defaultValue: "Edit" })}
            aria-label={t("admin.content.editPage", { defaultValue: "Edit page" })}
          >
            <EditOutlined className="size-3.5" />
          </Button>
          {p.status === "published" ? (
            <Button
              type="text"
              size="small"
              className="size-8 p-0"
              onClick={() => {
                setPublishError(null);
                setPublishTarget({ page: p, action: "unpublish" });
              }}
              title={t("admin.content.unpublish", { defaultValue: "Unpublish" })}
              aria-label={t("admin.content.unpublishPage", { defaultValue: "Unpublish page" })}
              disabled={unpublishMutation.isPending}
            >
              <CloseOutlined className="size-3.5" />
            </Button>
          ) : (
            <Button
              type="text"
              size="small"
              className="size-8 p-0"
              onClick={() => {
                setPublishError(null);
                setPublishTarget({ page: p, action: "publish" });
              }}
              title={t("admin.content.publish", { defaultValue: "Publish" })}
              aria-label={t("admin.content.publishPage", { defaultValue: "Publish page" })}
              disabled={publishMutation.isPending}
            >
              <SendOutlined className="size-3.5" />
            </Button>
          )}
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => setVersionsTarget(p)}
            title={t("admin.content.viewVersions", { defaultValue: "View Versions" })}
            aria-label={t("admin.content.viewVersionHistory", { defaultValue: "View version history" })}
          >
            <HistoryOutlined className="size-3.5" />
          </Button>
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => setDeleteTarget(p)}
            title={t("admin.content.delete", { defaultValue: "Delete" })}
            aria-label={t("admin.content.deletePage", { defaultValue: "Delete page" })}
          >
            <DeleteOutlined className="size-3.5 text-destructive" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <ProCard>
        <div className="pb-3">
          <Typography.Title level={5} className="flex items-center gap-2 text-sm">
            <FileTextOutlined className="size-4 text-primary" />
            {t("admin.content.staticPages", { defaultValue: "Static Pages" })}
          </Typography.Title>
        </div>
        <div>
          <p className="text-sm text-muted-foreground">
            {t("admin.content.staticPagesDesc", { defaultValue: "Manage static pages (e.g. About, Help, FAQ). Each edit creates a version snapshot that can be reviewed and restored." })}
          </p>
        </div>
      </ProCard>

      <StaticPageMigrationReport />

      {search.edit && requestedEditQuery.isPending && !requestedEditQuery.data ? (
        <Alert
          type="info"
          showIcon
          data-testid="content-edit-loading"
          title={t("admin.content.editLoading", { defaultValue: "Loading the requested page…" })}
        />
      ) : null}
      {search.edit && requestedEditQuery.isError ? (
        <Alert
          type="error"
          showIcon
          data-testid="content-edit-error"
          title={t("admin.content.editLoadError", { defaultValue: "The requested page could not be loaded." })}
          action={(
            <Button
              size="small"
              onClick={() => {
                openedEditId.current = search.edit;
                clearEditRoute();
              }}
            >
              {t("common.close", { defaultValue: "Close" })}
            </Button>
          )}
        />
      ) : null}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Select
            data-testid="pages-status-filter"
            value={statusFilter}
            onChange={(v) => {
              updateSearch({ ...search, status: v as typeof search.status, page: 1 });
            }}
            options={[
              { value: "all", label: t("admin.content.statusAll", { defaultValue: "All Statuses" }) },
              { value: "draft", label: t("admin.content.statusDraft", { defaultValue: "Draft" }) },
              { value: "published", label: t("admin.content.statusPublished", { defaultValue: "Published" }) },
              { value: "archived", label: t("admin.content.statusArchived", { defaultValue: "Archived" }) },
            ]}
          />
          {/* antd sets `width: 100%` on Input as unlayered CSS, so a Tailwind
              width class cannot size it inside a shrink-to-fit flex row.
              The wrapper owns the width; the input fills it. */}
          <div className="w-64">
            <Input
              data-testid="pages-category-filter"
              placeholder={t("admin.content.filterCategoryPlaceholder", { defaultValue: "Filter by category..." })}
              value={categoryFilter}
              onChange={(e) => {
                updateSearch({ ...search, category: e.target.value, page: 1 });
              }}
              className="h-9"
            />
          </div>
          <Badge color="secondary">
            {isError || !data ? "—" : t("admin.content.pageCount", { defaultValue: totalCount === 1 ? "{{count}} page" : "{{count}} pages", count: totalCount })}
          </Badge>
        </div>
        <Button data-testid="pages-new" onClick={openCreate}>
          <PlusOutlined className="size-4" />
          {t("admin.content.newPage", { defaultValue: "New Page" })}
        </Button>
      </div>

      <div data-testid="pages-table" data-state={pageListState}>
      {isError ? (
        /* A failed list request is not an empty page list. */
        <div
          role="alert"
          data-testid="content-pages-load-error"
          className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
        >
          {t("admin.content.loadError", { defaultValue: "The static pages could not be loaded." })}
        </div>
      ) : isLoading ? <Skeleton active /> : (
        <DataTable
          columns={columns}
          data={pages}
          rowKey={(p) => p.id}
          loading={isLoading}
          page={page}
          pageSize={20}
          total={totalCount}
          onPageChange={setPage}
          emptyTitle={t("admin.content.noPagesFound", { defaultValue: "No pages found" })}
          emptyDescription={t("admin.content.noPagesFoundDesc", { defaultValue: "Create a new static page to get started." })}
        />
      )}
      </div>

      {/* Create / Edit form */}
      <PageFormDialog
        editing={editing}
        open={formOpen}
        onOpenChange={(open) => {
          setFormOpen(open);
          if (!open) {
            setEditing(null);
            openedEditId.current = search.edit;
            clearEditRoute();
          }
        }}
        onSubmit={handleSubmit}
        loading={formLoading}
        error={formError}
      />

      {/* Delete confirmation */}
      {deleteTarget && (
        <ConfirmDialog
          open={Boolean(deleteTarget)}
          onOpenChange={(open) => {
            if (!open) {
              setDeleteTarget(null);
              setDeleteError(null);
            }
          }}
          title={t("admin.content.deletePageTitle", { defaultValue: "Delete Page" })}
          description={t("admin.content.deletePageConfirm", { defaultValue: 'Are you sure you want to delete "{{title}}"? This action cannot be undone.', title: deleteTarget.title_en })}
          confirmLabel={t("admin.content.delete", { defaultValue: "Delete" })}
          severity="destructive"
          onConfirm={() => deleteMutation.mutate(deleteTarget.id)}
          loading={deleteMutation.isPending}
          error={deleteError ? (
            <span data-testid="content-delete-error">
              {t("admin.content.deleteFailed", { defaultValue: "The page could not be deleted." })}
              {" "}
              {t("common.errorReason", {
                reason: deleteError,
                defaultValue: "Server response: {{reason}}",
              })}
            </span>
          ) : null}
        />
      )}

      {/* Publish / unpublish confirmation */}
      {publishTarget && (
        <ConfirmDialog
          open={Boolean(publishTarget)}
          onOpenChange={(open) => {
            if (!open) {
              setPublishTarget(null);
              setPublishError(null);
            }
          }}
          title={
            publishTarget.action === "publish"
              ? t("admin.content.publishTitle", { defaultValue: "Publish page" })
              : t("admin.content.unpublishTitle", { defaultValue: "Unpublish page" })
          }
          description={
            publishTarget.action === "publish"
              ? t("admin.content.publishConfirm", {
                  defaultValue: 'Publish "{{title}}"? It becomes visible on the public site.',
                  title: publishTarget.page.title_en,
                })
              : t("admin.content.unpublishConfirm", {
                  defaultValue: 'Unpublish "{{title}}"? It disappears from the public site.',
                  title: publishTarget.page.title_en,
                })
          }
          confirmLabel={
            publishTarget.action === "publish"
              ? t("admin.content.publish", { defaultValue: "Publish" })
              : t("admin.content.unpublish", { defaultValue: "Unpublish" })
          }
          severity={publishTarget.action === "unpublish" ? "destructive" : "default"}
          onConfirm={() => {
            if (publishTarget.action === "publish") {
              publishMutation.mutate(publishTarget.page.id);
            } else {
              unpublishMutation.mutate(publishTarget.page.id);
            }
          }}
          loading={publishMutation.isPending || unpublishMutation.isPending}
          error={publishError ? (
            <span data-testid="content-publish-error">
              {publishTarget.action === "publish"
                ? t("admin.content.publishFailed", { defaultValue: "The page could not be published." })
                : t("admin.content.unpublishFailed", { defaultValue: "The page could not be unpublished." })}
              {" "}
              {t("common.errorReason", {
                reason: publishError,
                defaultValue: "Server response: {{reason}}",
              })}
            </span>
          ) : null}
        />
      )}

      {/* Version history */}
      {versionsTarget && (
        <VersionHistoryDialog
          page={versionsTarget}
          open={Boolean(versionsTarget)}
          onOpenChange={(open) => !open && setVersionsTarget(null)}
          VersionDetail={VersionDetail}
        />
      )}
    </div>
  );
}
