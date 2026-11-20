import { DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { http } from "@soymutdb/api-client";
import { Skeleton, Badge, Button, Input, Select } from "@/lib/antd";
import { ConfirmDialog } from "../../components/confirm-dialog";
import { DataTable, type DataTableColumn } from "../../components/data-table";

type PageStatus = "draft" | "published" | "archived";
interface ContentItem { id: string; type: "news" | "publication"; title: string; slug: string; status: PageStatus; author: string | null; category: string | null; publishedAt: string | null; updatedAt: string; }

const TYPE_CONFIG = {
  news: { label: "News" },
  publication: { label: "Publication" },
} as const;

function statusBadgeVariant(status: PageStatus): "warning" | "success" | "secondary" {
  if (status === "published") return "success";
  if (status === "draft") return "warning";
  return "secondary";
}

/** ISO timestamps render as calendar dates; anything else is shown as sent. */
function formatContentDate(value: string | null): string {
  if (!value) return "—";
  return /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : value;
}

const PAGE_SIZE = 20;

type NewsStatusFilter = "all" | PageStatus;
type FeaturedFilter = "all" | "featured" | "unfeatured";

export function NewsPublicationTab({ type }: { type: "news" | "publication" }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [deleteTarget, setDeleteTarget] = React.useState<ContentItem | null>(
    null,
  );
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [page, setPage] = React.useState(1);
  const [searchInput, setSearchInput] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState<NewsStatusFilter>("all");
  const [featuredFilter, setFeaturedFilter] = React.useState<FeaturedFilter>("all");
  const isNews = type === "news";
  const isPublication = type === "publication";

  // Typing must not fire a request per keystroke; the list query only follows
  // the debounced term.
  React.useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  // Switching tabs reuses this component instance: reset page and filters so
  // the previous tab's state cannot leak into the next one.
  React.useEffect(() => {
    setPage(1);
    setSearchInput("");
    setSearch("");
    setStatusFilter("all");
    setFeaturedFilter("all");
  }, [type]);

  React.useEffect(() => {
    setPage(1);
  }, [search, statusFilter, featuredFilter]);

  const { data, isLoading, isError } = useQuery<{ items: ContentItem[]; total: number }>(
    {
      queryKey: ["admin-content", type, page, search, statusFilter, featuredFilter],
      queryFn: async () => {
        if (isNews) {
          const response = await http.get<{
            items: Array<{
              id: string;
              title_en: string;
              slug: string;
              status: string;
              category: string | null;
              published_at: string | null;
              updated_at: string;
            }>;
            total: number;
          }>("/admin/news", {
            params: {
              page,
              page_size: PAGE_SIZE,
              search: search || undefined,
              status_filter: statusFilter === "all" ? undefined : statusFilter,
            },
          });
          return {
            items: response.items.map((item): ContentItem => ({
              id: item.id,
              type: "news",
              title: item.title_en,
              slug: item.slug,
              status: (item.status as PageStatus) || "draft",
              author: null,
              category: item.category ?? null,
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
        }>("/admin/publications", {
          params: {
            page,
            page_size: PAGE_SIZE,
            search: search || undefined,
            is_featured:
              featuredFilter === "all" ? undefined : featuredFilter === "featured",
          },
        });
        return {
          items: response.items.map((item): ContentItem => ({
            id: item.id,
            type: "publication",
            title: item.title,
            slug: item.doi ?? item.title,
            status: "published",
            author: item.authors || null,
            category: null,
            publishedAt: item.year != null ? String(item.year) : null,
            updatedAt: item.created_at,
          })),
          total: response.total,
        };
      },
    },
  );

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      http.delete(isNews ? `/admin/news/${id}` : `/admin/publications/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-content"] });
      setDeleteTarget(null);
      setDeleteError(null);
    },
    onError: (error) => {
      // The dialog stays open and explains the refusal; a rejected delete used
      // to be indistinguishable from a successful one.
      setDeleteError(error instanceof Error ? error.message : String(error));
    },
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const hasActiveFilters =
    search.length > 0 || statusFilter !== "all" || featuredFilter !== "all";

  // Deleting the last row of a page would otherwise leave an empty page with
  // no way back except the pager; step back automatically.
  React.useEffect(() => {
    if (!isLoading && page > 1 && data && data.items.length === 0 && data.total > 0) {
      setPage((current) => Math.max(1, current - 1));
    }
  }, [data, isLoading, page]);

  const config = TYPE_CONFIG[type];
  const typeLabel = t(`admin.content.type.${type}`, { defaultValue: config.label });

  const columns: DataTableColumn<ContentItem>[] = [
    {
      key: "title",
      header: t("admin.content.colTitle", { defaultValue: "Title" }),
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
      header: t("admin.content.colStatus", { defaultValue: "Status" }),
      sortable: true,
      sortAccessor: (c) => c.status,
      cell: (c) => (
        <Badge color={statusBadgeVariant(c.status)}>{t(`admin.content.status.${c.status}`, { defaultValue: c.status })}</Badge>
      ),
    },
    ...(isNews
      ? [
          {
            key: "category",
            header: t("admin.content.colCategory", { defaultValue: "Category" }),
            sortable: true,
            sortAccessor: (c: ContentItem) => c.category ?? "",
            cell: (c: ContentItem) => (
              <span className="text-sm">{c.category ?? "—"}</span>
            ),
          } satisfies DataTableColumn<ContentItem>,
        ]
      : [
          {
            key: "author",
            header: t("admin.content.colAuthor", { defaultValue: "Author" }),
            sortable: true,
            sortAccessor: (c: ContentItem) => c.author ?? "",
            cell: (c: ContentItem) => (
              <span className="text-sm">{c.author ?? "—"}</span>
            ),
          } satisfies DataTableColumn<ContentItem>,
        ]),
    {
      key: "publishedAt",
      header: t("admin.content.colPublished", { defaultValue: "Published" }),
      sortable: true,
      sortAccessor: (c) => c.publishedAt ?? "",
      cell: (c) => (
        <span className="text-sm text-muted-foreground">
          {formatContentDate(c.publishedAt)}
        </span>
      ),
    },
    {
      key: "updatedAt",
      header: t("admin.content.colUpdated", { defaultValue: "Updated" }),
      sortable: true,
      sortAccessor: (c) => c.updatedAt,
      cell: (c) => (
        <span className="text-sm text-muted-foreground">
          {formatContentDate(c.updatedAt)}
        </span>
      ),
    },
    {
      key: "actions",
      header: t("admin.content.colActions", { defaultValue: "Actions" }),
      align: "right",
      cell: (c) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            title={t("admin.content.edit", { defaultValue: "Edit" })}
            aria-label={t("admin.content.editContent", { defaultValue: "Edit content" })}
            onClick={() => {
              if (isNews) {
                navigate({ to: "/news/$id", params: { id: c.id } });
              } else if (isPublication) {
                navigate({ to: "/publications", search: { edit: c.id } });
              }
            }}
          >
            <EditOutlined className="size-3.5" />
          </Button>
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => setDeleteTarget(c)}
            title={t("admin.content.delete", { defaultValue: "Delete" })}
            aria-label={t("admin.content.deleteContent", { defaultValue: "Delete content" })}
          >
            <DeleteOutlined className="size-3.5 text-destructive" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Input
            data-testid="content-search"
            allowClear
            placeholder={t("admin.content.searchPlaceholder", { defaultValue: "Search by title…" })}
            aria-label={t("admin.content.searchContent", { defaultValue: "Search content" })}
            prefix={<SearchOutlined className="text-muted-foreground" />}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            className="w-64"
          />
          {isNews ? (
            <Select
              data-testid="content-status-filter"
              aria-label={t("admin.content.filterStatus", { defaultValue: "Filter by status" })}
              value={statusFilter}
              onChange={(value) => setStatusFilter(value as NewsStatusFilter)}
              options={[
                { value: "all", label: t("admin.content.statusAll", { defaultValue: "All statuses" }) },
                { value: "draft", label: t("admin.content.status.draft", { defaultValue: "draft" }) },
                { value: "published", label: t("admin.content.status.published", { defaultValue: "published" }) },
                { value: "archived", label: t("admin.content.status.archived", { defaultValue: "archived" }) },
              ]}
              className="w-40"
            />
          ) : (
            <Select
              data-testid="content-featured-filter"
              aria-label={t("admin.content.filterFeatured", { defaultValue: "Filter by featured status" })}
              value={featuredFilter}
              onChange={(value) => setFeaturedFilter(value as FeaturedFilter)}
              options={[
                { value: "all", label: t("admin.content.featuredAll", { defaultValue: "All publications" }) },
                { value: "featured", label: t("admin.content.featuredOnly", { defaultValue: "Featured only" }) },
                { value: "unfeatured", label: t("admin.content.unfeaturedOnly", { defaultValue: "Not featured" }) },
              ]}
              className="w-40"
            />
          )}
        </div>
        <div className="flex items-center gap-2">
          <Badge color="secondary">
            {isError || !data ? "—" : t("admin.content.itemCount", { defaultValue: items.length === 1 ? "{{count}} {{type}}" : "{{count}} {{type}}s", count: total, type: typeLabel })}
          </Badge>
          <Button
            onClick={() => {
              if (isNews) {
                navigate({ to: "/news/new" });
              } else if (isPublication) {
                navigate({ to: "/publications" });
              }
            }}
          >
            <PlusOutlined className="size-4" />
            {t("admin.content.newType", { defaultValue: "New {{type}}", type: typeLabel })}
          </Button>
        </div>
      </div>

      {isError ? (
        /* A failed list request is not an empty content list. */
        <div
          role="alert"
          data-testid="content-list-load-error"
          className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
        >
          {t("admin.content.loadError", { defaultValue: "The content list could not be loaded." })}
        </div>
      ) : isLoading ? <Skeleton active /> : (
        <DataTable
          columns={columns}
          data={items}
          rowKey={(c) => c.id}
          loading={isLoading}
          page={page}
          pageSize={PAGE_SIZE}
          total={total}
          onPageChange={setPage}
          emptyTitle={
            hasActiveFilters
              ? t("admin.content.noMatchingContent", { defaultValue: "No matching {{type}} content", type: typeLabel.toLowerCase() })
              : t("admin.content.noTypeContent", { defaultValue: "No {{type}} content", type: typeLabel.toLowerCase() })
          }
          emptyDescription={
            hasActiveFilters
              ? t("admin.content.noMatchingContentDesc", { defaultValue: "Clear the search or filters to see everything." })
              : t("admin.content.noTypeContentDesc", { defaultValue: "Create a new {{type}} to get started.", type: typeLabel.toLowerCase() })
          }
        />
      )}

      {deleteTarget && (
        <ConfirmDialog
          open={Boolean(deleteTarget)}
          onOpenChange={(open) => {
            if (!open) {
              setDeleteTarget(null);
              setDeleteError(null);
            }
          }}
          title={t("admin.content.deleteContentTitle", { defaultValue: "Delete Content" })}
          description={t("admin.content.deleteContentConfirm", { defaultValue: 'Are you sure you want to delete "{{title}}"? This action cannot be undone.', title: deleteTarget.title })}
          confirmLabel={t("admin.content.delete", { defaultValue: "Delete" })}
          severity="destructive"
          onConfirm={() => deleteMutation.mutate(deleteTarget.id)}
          loading={deleteMutation.isPending}
          error={deleteError ? (
            <span data-testid="content-delete-error">
              {t("admin.content.deleteContentFailed", { defaultValue: "The content could not be deleted." })}
              {" "}
              {t("common.errorReason", {
                reason: deleteError,
                defaultValue: "Server response: {{reason}}",
              })}
            </span>
          ) : null}
        />
      )}
    </div>
  );
}
