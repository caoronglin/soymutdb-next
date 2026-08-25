import { ReadOutlined, EyeOutlined, FileTextOutlined, HistoryOutlined, EditOutlined, PlusOutlined, RedoOutlined, SaveOutlined, SendOutlined, DeleteOutlined, CloseOutlined } from "@ant-design/icons";
import * as React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { http } from "@soymutdb/api-client";
import { Modal, Typography, Badge, Button, Card, Input, Select } from "@/lib/antd";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { ConfirmDialog } from "../components/confirm-dialog";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentType = "news" | "publication" | "page";
type PageStatus = "draft" | "published" | "archived";

interface ContentItem {
  id: string;
  type: ContentType;
  title: string;
  slug: string;
  status: PageStatus;
  author: string;
  publishedAt: string | null;
  updatedAt: string;
}

interface StaticPage {
  id: string;
  slug: string;
  title_en: string;
  title_zh: string | null;
  content_en: string;
  content_zh: string | null;
  summary: string | null;
  category: string | null;
  status: PageStatus;
  sort_order: number;
  author_name: string | null;
  published_at: string | null;
  current_version: number;
  created_at: string;
  updated_at: string;
}

interface StaticPageCreate {
  slug: string;
  title_en: string;
  title_zh?: string;
  content_en: string;
  content_zh?: string;
  summary?: string;
  category?: string;
  sort_order?: number;
  status?: PageStatus;
  edit_comment?: string;
}

interface StaticPageUpdate {
  title_en?: string;
  title_zh?: string;
  content_en?: string;
  content_zh?: string;
  summary?: string;
  category?: string;
  sort_order?: number;
  edit_comment?: string;
}

interface ContentVersion {
  id: string;
  page_id: string;
  version: number;
  title_en: string;
  title_zh: string | null;
  content_en: string;
  content_zh: string | null;
  summary: string | null;
  edited_by: string | null;
  edit_comment: string | null;
  created_at: string;
}

interface PageListResponse {
  items: StaticPage[];
  total: number;
}

interface PageFormValues {
  slug: string;
  title_en: string;
  title_zh: string;
  content_en: string;
  content_zh: string;
  summary: string;
  category: string;
  sort_order: string;
  status: PageStatus;
  edit_comment: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TYPE_CONFIG: Record<ContentType, { label: string; icon: typeof ReadOutlined }> = {
  news: { label: "News", icon: ReadOutlined },
  publication: { label: "Publication", icon: ReadOutlined },
  page: { label: "Pages", icon: FileTextOutlined },
};

function statusBadgeVariant(
  status: PageStatus,
): "warning" | "success" | "secondary" {
  if (status === "published") return "success";
  if (status === "draft") return "warning";
  return "secondary";
}

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "An unknown error occurred";
}

function initFormValues(editing: StaticPage | null): PageFormValues {
  if (editing) {
    return {
      slug: editing.slug,
      title_en: editing.title_en,
      title_zh: editing.title_zh ?? "",
      content_en: editing.content_en,
      content_zh: editing.content_zh ?? "",
      summary: editing.summary ?? "",
      category: editing.category ?? "",
      sort_order: String(editing.sort_order ?? 0),
      status: editing.status === "published" ? "published" : "draft",
      edit_comment: "",
    };
  }
  return {
    slug: "",
    title_en: "",
    title_zh: "",
    content_en: "",
    content_zh: "",
    summary: "",
    category: "",
    sort_order: "0",
    status: "draft",
    edit_comment: "",
  };
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ContentPage() {
  const [tab, setTab] = React.useState<ContentType>("page");

  return (
    <div className="space-y-6">
      <div><Typography.Title level={2}>Content Management</Typography.Title><Typography.Text type="secondary">Manage static pages, news articles, and publications with full version history.</Typography.Text></div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-border">
        {(Object.keys(TYPE_CONFIG) as ContentType[]).map((t) => {
          const Icon = TYPE_CONFIG[t].icon;
          return (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
                tab === t
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="size-3.5" />
              {TYPE_CONFIG[t].label}
            </button>
          );
        })}
      </div>

      {tab === "page" && <PagesTab />}
      {tab === "news" && <NewsPublicationTab type="news" />}
      {tab === "publication" && <NewsPublicationTab type="publication" />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pages tab — full CRUD + version management
// ---------------------------------------------------------------------------

function PagesTab() {
  const queryClient = useQueryClient();
  const [page, setPage] = React.useState(1);
  const [statusFilter, setStatusFilter] = React.useState<string>("all");
  const [categoryFilter, setCategoryFilter] = React.useState<string>("");
  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<StaticPage | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<StaticPage | null>(null);
  const [versionsTarget, setVersionsTarget] = React.useState<StaticPage | null>(
    null,
  );

  const { data, isLoading } = useQuery<PageListResponse>({
    queryKey: ["admin-pages", page, statusFilter, categoryFilter],
    queryFn: () =>
      http.get<PageListResponse>("/admin/content/pages", {
        params: {
          page,
          page_size: 20,
          status: statusFilter !== "all" ? statusFilter : undefined,
          category: categoryFilter || undefined,
        },
      }),
    placeholderData: { items: [], total: 0 },
  });

  const createMutation = useMutation({
    mutationFn: (payload: StaticPageCreate) =>
      http.post("/admin/content/pages", { json: payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-pages"] });
      setFormOpen(false);
      setEditing(null);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (params: { id: string; payload: StaticPageUpdate }) =>
      http.put(`/admin/content/pages/${params.id}`, { json: params.payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-pages"] });
      setFormOpen(false);
      setEditing(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => http.delete(`/admin/content/pages/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-pages"] });
      setDeleteTarget(null);
    },
  });

  const publishMutation = useMutation({
    mutationFn: (id: string) =>
      http.post(`/admin/content/pages/${id}/publish`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-pages"] });
    },
  });

  const unpublishMutation = useMutation({
    mutationFn: (id: string) =>
      http.post(`/admin/content/pages/${id}/unpublish`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-pages"] });
    },
  });

  const openCreate = () => {
    createMutation.reset();
    updateMutation.reset();
    setEditing(null);
    setFormOpen(true);
  };

  const openEdit = (p: StaticPage) => {
    createMutation.reset();
    updateMutation.reset();
    setEditing(p);
    setFormOpen(true);
  };

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

  const columns: DataTableColumn<StaticPage>[] = [
    {
      key: "title",
      header: "Title",
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
      header: "Slug",
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
      header: "Category",
      sortable: true,
      sortAccessor: (p) => p.category ?? "",
      cell: (p) => <span className="text-sm">{p.category ?? "—"}</span>,
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortAccessor: (p) => p.status,
      cell: (p) => (
        <Badge color={statusBadgeVariant(p.status)}>{p.status}</Badge>
      ),
    },
    {
      key: "updated_at",
      header: "Updated",
      sortable: true,
      sortAccessor: (p) => p.updated_at,
      cell: (p) => (
        <span className="text-sm text-muted-foreground">{p.updated_at}</span>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: (p) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => openEdit(p)}
            title="Edit"
            aria-label="Edit page"
          >
            <EditOutlined className="size-3.5" />
          </Button>
          {p.status === "published" ? (
            <Button
              type="text"
              size="small"
              className="size-8 p-0"
              onClick={() => unpublishMutation.mutate(p.id)}
              title="Unpublish"
              aria-label="Unpublish page"
              disabled={unpublishMutation.isPending}
            >
              <CloseOutlined className="size-3.5" />
            </Button>
          ) : (
            <Button
              type="text"
              size="small"
              className="size-8 p-0"
              onClick={() => publishMutation.mutate(p.id)}
              title="Publish"
              aria-label="Publish page"
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
            title="View Versions"
            aria-label="View version history"
          >
            <HistoryOutlined className="size-3.5" />
          </Button>
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => setDeleteTarget(p)}
            title="Delete"
            aria-label="Delete page"
          >
            <DeleteOutlined className="size-3.5 text-destructive" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <Card>
        <div className="pb-3">
          <Typography.Title level={5} className="flex items-center gap-2 text-sm">
            <FileTextOutlined className="size-4 text-primary" />
            Static Pages
          </Typography.Title>
        </div>
        <div>
          <p className="text-sm text-muted-foreground">
            Manage static pages (e.g. About, Help, FAQ). Each edit creates a
            version snapshot that can be reviewed and restored.
          </p>
        </div>
      </Card>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Select
            value={statusFilter}
            onChange={(v) => {
              setStatusFilter(v);
              setPage(1);
            }}
          >


              <Select.Option value="all">All Statuses</Select.Option>
              <Select.Option value="draft">Draft</Select.Option>
              <Select.Option value="published">Published</Select.Option>
              <Select.Option value="archived">Archived</Select.Option>

          </Select>
          <Input
            placeholder="Filter by category..."
            value={categoryFilter}
            onChange={(e) => {
              setCategoryFilter(e.target.value);
              setPage(1);
            }}
            className="h-9 max-w-xs"
          />
          <Badge color="secondary">
            {totalCount} page{totalCount === 1 ? "" : "s"}
          </Badge>
        </div>
        <Button onClick={openCreate}>
          <PlusOutlined className="size-4" />
          New Page
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={pages}
        rowKey={(p) => p.id}
        loading={isLoading}
        page={page}
        pageSize={20}
        total={totalCount}
        onPageChange={setPage}
        emptyTitle="No pages found"
        emptyDescription="Create a new static page to get started."
      />

      {/* Create / Edit form */}
      <PageFormDialog
        editing={editing}
        open={formOpen}
        onOpenChange={(open) => {
          setFormOpen(open);
          if (!open) setEditing(null);
        }}
        onSubmit={handleSubmit}
        loading={formLoading}
        error={formError}
      />

      {/* Delete confirmation */}
      {deleteTarget && (
        <ConfirmDialog
          open={Boolean(deleteTarget)}
          onOpenChange={(open) => !open && setDeleteTarget(null)}
          title="Delete Page"
          description={`Are you sure you want to delete "${deleteTarget.title_en}"? This action cannot be undone.`}
          confirmLabel="Delete"
          severity="destructive"
          onConfirm={() => deleteMutation.mutate(deleteTarget.id)}
          loading={deleteMutation.isPending}
        />
      )}

      {/* Version history */}
      {versionsTarget && (
        <VersionHistoryDialog
          page={versionsTarget}
          open={Boolean(versionsTarget)}
          onOpenChange={(open) => !open && setVersionsTarget(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page create/edit form dialog
// ---------------------------------------------------------------------------

function PageFormDialog({
  editing,
  open,
  onOpenChange,
  onSubmit,
  loading,
  error,
}: {
  editing: StaticPage | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: PageFormValues) => void;
  loading: boolean;
  error: unknown;
}) {
  const isEdit = editing !== null;
  const [values, setValues] = React.useState<PageFormValues>(() =>
    initFormValues(editing),
  );

  React.useEffect(() => {
    if (open) {
      setValues(initFormValues(editing));
    }
  }, [editing, open]);

  const setField = <K extends keyof PageFormValues>(
    key: K,
    val: PageFormValues[K],
  ) => {
    setValues((prev) => ({ ...prev, [key]: val }));
  };

  const canSubmit =
    values.title_en.trim() !== "" &&
    values.slug.trim() !== "" &&
    values.content_en.trim() !== "" &&
    !loading;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit(values);
  };

  return (
    <Modal open={open} onCancel={() => onOpenChange(false)}>
      <div className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <div>
          <Typography.Title level={5}>{isEdit ? "Edit Page" : "New Page"}</Typography.Title>
          <Typography.Text type="secondary">
            {isEdit
              ? `Editing "${editing?.title_en}". Bilingual content (EN/ZH) supported.`
              : "Create a new static page. Bilingual content (EN/ZH) supported."}
          </Typography.Text>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-title-en">Title (English) *</label>
              <Input
                id="page-title-en"
                value={values.title_en}
                onChange={(e) => setField("title_en", e.target.value)}
                placeholder="Page title in English"
                required
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-title-zh">Title (Chinese)</label>
              <Input
                id="page-title-zh"
                value={values.title_zh}
                onChange={(e) => setField("title_zh", e.target.value)}
                placeholder="页面标题（中文）"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="page-slug">Slug *</label>
              <Input
                id="page-slug"
                value={values.slug}
                onChange={(e) => setField("slug", e.target.value)}
                placeholder="about-us"
                disabled={isEdit}
                required
              />
              {isEdit ? (
                <p className="text-xs text-muted-foreground">
                  Slug cannot be changed after creation.
                </p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <label htmlFor="page-category">Category</label>
              <Input
                id="page-category"
                value={values.category}
                onChange={(e) => setField("category", e.target.value)}
                placeholder="about, help, etc."
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="page-sort">Sort Order</label>
              <Input
                id="page-sort"
                type="number"
                value={values.sort_order}
                onChange={(e) => setField("sort_order", e.target.value)}
                placeholder="0"
              />
            </div>
            {!isEdit ? (
              <div className="space-y-1.5">
                <label htmlFor="page-status">Status</label>
                <Select
                  value={values.status}
                  onChange={(v) => setField("status", v as PageStatus)}
                >


                    <Select.Option value="draft">Draft</Select.Option>
                    <Select.Option value="published">Published</Select.Option>

                </Select>
              </div>
            ) : null}
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-summary">Summary</label>
              <Input
                id="page-summary"
                value={values.summary}
                onChange={(e) => setField("summary", e.target.value)}
                placeholder="Short summary for listings"
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-content-en">Content (English) *</label>
              <Input.TextArea
                id="page-content-en"
                value={values.content_en}
                onChange={(e) => setField("content_en", e.target.value)}
                placeholder="Page content in English (Markdown supported)"
                className="min-h-[160px] font-mono text-sm"
                required
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-content-zh">Content (Chinese)</label>
              <Input.TextArea
                id="page-content-zh"
                value={values.content_zh}
                onChange={(e) => setField("content_zh", e.target.value)}
                placeholder="页面内容（中文）"
                className="min-h-[160px] font-mono text-sm"
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-comment">Edit Comment</label>
              <Input
                id="page-comment"
                value={values.edit_comment}
                onChange={(e) => setField("edit_comment", e.target.value)}
                placeholder={
                  isEdit ? "Describe this revision" : "Initial version note"
                }
              />
              <p className="text-xs text-muted-foreground">
                Saved with the version history for tracking changes.
              </p>
            </div>
          </div>

          {error ? (
            <p className="text-sm text-destructive" role="alert">
              {getErrorMessage(error)}
            </p>
          ) : null}

          <div>
            <Button
              type="default"
              onClick={() => onOpenChange(false)}
              disabled={loading}
            >
              Cancel
            </Button>
            <Button htmlType="submit" disabled={!canSubmit}>
              {loading ? (
                "Saving…"
              ) : (
                <>
                  <SaveOutlined className="size-4" />
                  {isEdit ? "SaveOutlined Changes" : "Create Page"}
                </>
              )}
            </Button>
          </div>
        </form>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Version history dialog
// ---------------------------------------------------------------------------

function VersionHistoryDialog({
  page,
  open,
  onOpenChange,
}: {
  page: StaticPage;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [viewing, setViewing] = React.useState<ContentVersion | null>(null);
  const [restoreTarget, setRestoreTarget] =
    React.useState<ContentVersion | null>(null);

  const { data, isLoading } = useQuery<ContentVersion[]>({
    queryKey: ["admin-page-versions", page.id],
    queryFn: async () => {
      const res = await http.get<
        ContentVersion[] | { items: ContentVersion[] }
      >(`/admin/content/pages/${page.id}/versions`);
      return Array.isArray(res) ? res : res.items;
    },
    enabled: open,
  });

  const restoreMutation = useMutation({
    mutationFn: (version: number) =>
      http.post(
        `/admin/content/pages/${page.id}/versions/${version}/restore`,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-pages"] });
      queryClient.invalidateQueries({
        queryKey: ["admin-page-versions", page.id],
      });
      setRestoreTarget(null);
      setViewing(null);
    },
  });

  React.useEffect(() => {
    if (!open) {
      setViewing(null);
      setRestoreTarget(null);
    }
  }, [open]);

  const versions = data ?? [];

  const versionColumns: DataTableColumn<ContentVersion>[] = [
    {
      key: "version",
      header: "Version",
      sortable: true,
      sortAccessor: (v) => v.version,
      cell: (v) => (
        <span className="font-mono text-sm font-medium">v{v.version}</span>
      ),
    },
    {
      key: "title_en",
      header: "Title",
      sortable: true,
      sortAccessor: (v) => v.title_en,
      cell: (v) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{v.title_en}</p>
          {v.title_zh ? (
            <p className="truncate text-xs text-muted-foreground">
              {v.title_zh}
            </p>
          ) : null}
        </div>
      ),
    },
    {
      key: "edit_comment",
      header: "Comment",
      cell: (v) => (
        <span className="text-sm text-muted-foreground">
          {v.edit_comment ?? "—"}
        </span>
      ),
    },
    {
      key: "edited_by",
      header: "Edited By",
      sortable: true,
      sortAccessor: (v) => v.edited_by ?? "",
      cell: (v) => <span className="text-sm">{v.edited_by ?? "—"}</span>,
    },
    {
      key: "created_at",
      header: "Created",
      sortable: true,
      sortAccessor: (v) => v.created_at,
      cell: (v) => (
        <span className="text-sm text-muted-foreground">{v.created_at}</span>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: (v) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => setViewing(v)}
            title="View"
            aria-label="View version content"
          >
            <EyeOutlined className="size-3.5" />
          </Button>
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => setRestoreTarget(v)}
            title="Restore"
            aria-label="Restore version"
            disabled={v.version === page.current_version}
          >
            <RedoOutlined className="size-3.5" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <Modal open={open} onCancel={() => onOpenChange(false)}>
      <div className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <div>
          <Typography.Title level={5} className="flex items-center gap-2">
            <HistoryOutlined className="size-5" />
            Version HistoryOutlined
          </Typography.Title>
          <Typography.Text type="secondary">
            <span className="font-medium text-foreground">{page.title_en}</span>
            {" · "}current version v{page.current_version}
          </Typography.Text>
        </div>

        {viewing ? (
          <VersionDetail version={viewing} onBack={() => setViewing(null)} />
        ) : (
          <DataTable
            columns={versionColumns}
            data={versions}
            rowKey={(v) => v.id}
            loading={isLoading}
            emptyTitle="No versions found"
            emptyDescription="Versions are created automatically when a page is edited."
          />
        )}

        <div>
          <Button type="default" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </div>
      </div>

      {restoreTarget && (
        <ConfirmDialog
          open={Boolean(restoreTarget)}
          onOpenChange={(open) => !open && setRestoreTarget(null)}
          title="Restore Version"
          description={`Restore page "${page.title_en}" to version v${restoreTarget.version}? This creates a new version with the content of v${restoreTarget.version}.`}
          confirmLabel="Restore"
          severity="destructive"
          onConfirm={() => restoreMutation.mutate(restoreTarget.version)}
          loading={restoreMutation.isPending}
        >
          {restoreMutation.error ? (
            <p className="text-sm text-destructive" role="alert">
              {getErrorMessage(restoreMutation.error)}
            </p>
          ) : null}
        </ConfirmDialog>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Version detail (inline within version history dialog)
// ---------------------------------------------------------------------------

function VersionDetail({
  version,
  onBack,
}: {
  version: ContentVersion;
  onBack: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button type="text" size="small" onClick={onBack}>
          Back to list
        </Button>
        <span className="font-mono text-sm font-medium">v{version.version}</span>
        {version.edit_comment ? (
          <span className="text-sm text-muted-foreground">
            · {version.edit_comment}
          </span>
        ) : null}
      </div>

      <div className="grid gap-3 rounded-lg border border-border bg-muted/30 p-4 text-sm sm:grid-cols-2">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Edited By
          </p>
          <p className="font-medium">{version.edited_by ?? "—"}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Created
          </p>
          <p className="font-medium">{version.created_at}</p>
        </div>
      </div>

      <div className="space-y-1.5">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          Title (English)
        </p>
        <p className="font-medium">{version.title_en}</p>
      </div>
      {version.title_zh ? (
        <div className="space-y-1.5">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Title (Chinese)
          </p>
          <p className="font-medium">{version.title_zh}</p>
        </div>
      ) : null}
      {version.summary ? (
        <div className="space-y-1.5">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Summary
          </p>
          <p className="text-sm">{version.summary}</p>
        </div>
      ) : null}
      <div className="space-y-1.5">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          Content (English)
        </p>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs">
          {version.content_en}
        </pre>
      </div>
      {version.content_zh ? (
        <div className="space-y-1.5">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Content (Chinese)
          </p>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs">
            {version.content_zh}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// News / Publication tab — list view (existing behaviour)
// ---------------------------------------------------------------------------

function NewsPublicationTab({ type }: { type: "news" | "publication" }) {
  const queryClient = useQueryClient();
  const [deleteTarget, setDeleteTarget] = React.useState<ContentItem | null>(
    null,
  );
  const isNews = type === "news";

  const { data, isLoading } = useQuery<{ items: ContentItem[]; total: number }>(
    {
      queryKey: ["admin-content", type],
      queryFn: async () => {
        if (isNews) {
          const response = await http.get<{
            items: Array<{
              id: string;
              title_en: string;
              slug: string;
              status: string;
              published_at: string | null;
              updated_at: string;
            }>;
            total: number;
          }>("/admin/news", { params: { page: 1, page_size: 20 } });
          return {
            items: response.items.map((item): ContentItem => ({
              id: item.id,
              type: "news",
              title: item.title_en,
              slug: item.slug,
              status: (item.status as PageStatus) || "draft",
              author: "—",
              publishedAt: item.published_at ?? null,
              updatedAt: item.updated_at,
            })),
            total: response.total,
          };
        }

        const response = await http.get<{
          items: Array<{
            id: string;
            title: string;
            authors: string;
            year: number | null;
            doi: string | null;
            created_at: string;
          }>;
          total: number;
        }>("/admin/publications", { params: { page: 1, page_size: 20 } });
        return {
          items: response.items.map((item): ContentItem => ({
            id: item.id,
            type: "publication",
            title: item.title,
            slug: item.doi ?? item.title,
            status: "published",
            author: item.authors,
            publishedAt: item.year != null ? String(item.year) : null,
            updatedAt: item.created_at,
          })),
          total: response.total,
        };
      },
      placeholderData: { items: [], total: 0 },
    },
  );

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      http.delete(isNews ? `/admin/news/${id}` : `/admin/publications/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-content"] });
      setDeleteTarget(null);
    },
  });

  const items = data?.items ?? [];
  const config = TYPE_CONFIG[type];

  const columns: DataTableColumn<ContentItem>[] = [
    {
      key: "title",
      header: "Title",
      sortable: true,
      sortAccessor: (c) => c.title,
      cell: (c) => (
        <div>
          <p className="font-medium">{c.title}</p>
          <p className="font-mono text-xs text-muted-foreground">/{c.slug}</p>
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortAccessor: (c) => c.status,
      cell: (c) => (
        <Badge color={statusBadgeVariant(c.status)}>{c.status}</Badge>
      ),
    },
    {
      key: "author",
      header: "Author",
      sortable: true,
      sortAccessor: (c) => c.author,
      cell: (c) => <span className="text-sm">{c.author}</span>,
    },
    {
      key: "publishedAt",
      header: "Published",
      sortable: true,
      sortAccessor: (c) => c.publishedAt ?? "",
      cell: (c) => (
        <span className="text-sm text-muted-foreground">
          {c.publishedAt ?? "—"}
        </span>
      ),
    },
    {
      key: "updatedAt",
      header: "Updated",
      sortable: true,
      sortAccessor: (c) => c.updatedAt,
      cell: (c) => (
        <span className="text-sm text-muted-foreground">{c.updatedAt}</span>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: (c) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            title="Edit"
            aria-label="Edit content"
          >
            <EditOutlined className="size-3.5" />
          </Button>
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => setDeleteTarget(c)}
            title="Delete"
            aria-label="Delete content"
          >
            <DeleteOutlined className="size-3.5 text-destructive" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Badge color="secondary">
          {items.length} {config.label.toLowerCase()}
          {items.length === 1 ? "" : "s"}
        </Badge>
        <Button>
          <PlusOutlined className="size-4" />
          New {config.label}
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={items}
        rowKey={(c) => c.id}
        loading={isLoading}
        emptyTitle={`No ${config.label.toLowerCase()} content`}
        emptyDescription={`Create a new ${config.label.toLowerCase()} to get started.`}
      />

      {deleteTarget && (
        <ConfirmDialog
          open={Boolean(deleteTarget)}
          onOpenChange={(open) => !open && setDeleteTarget(null)}
          title="Delete Content"
          description={`Are you sure you want to delete "${deleteTarget.title}"? This action cannot be undone.`}
          confirmLabel="Delete"
          severity="destructive"
          onConfirm={() => deleteMutation.mutate(deleteTarget.id)}
          loading={deleteMutation.isPending}
        />
      )}
    </div>
  );
}
