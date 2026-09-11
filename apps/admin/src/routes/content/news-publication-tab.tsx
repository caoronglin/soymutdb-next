import { DeleteOutlined, EditOutlined, EyeOutlined, PlusOutlined } from "@ant-design/icons";
import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { http } from "@soymutdb/api-client";
import { Badge, Button, Card, Input, Select, Typography } from "@/lib/antd";
import { ConfirmDialog } from "../../components/confirm-dialog";
import { DataTable, type DataTableColumn } from "../../components/data-table";

type PageStatus = "draft" | "published" | "archived";
interface ContentItem { id: string; type: "news" | "publication" | "page"; title: string; slug: string; status: PageStatus; author: string; publishedAt: string | null; updatedAt: string; }

const TYPE_CONFIG = {
  news: { label: "News" },
  publication: { label: "Publication" },
} as const;

function statusBadgeVariant(status: PageStatus): "warning" | "success" | "secondary" {
  if (status === "published") return "success";
  if (status === "draft") return "warning";
  return "secondary";
}

function getErrorMessage(err: unknown, t: (key: string, options?: Record<string, unknown>) => string): string {
  if (err instanceof Error) return err.message;
  return t("admin.content.unknownError", { defaultValue: "An unknown error occurred" });
}

export function NewsPublicationTab({ type }: { type: "news" | "publication" }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [deleteTarget, setDeleteTarget] = React.useState<ContentItem | null>(
    null,
  );
  const isNews = type === "news";
  const isPublication = type === "publication";

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
  const typeLabel = t(`admin.content.type_${type}`, { defaultValue: config.label });

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
        <Badge color={statusBadgeVariant(c.status)}>{t(`admin.content.status_${c.status}`, { defaultValue: c.status })}</Badge>
      ),
    },
    {
      key: "author",
      header: t("admin.content.colAuthor", { defaultValue: "Author" }),
      sortable: true,
      sortAccessor: (c) => c.author,
      cell: (c) => <span className="text-sm">{c.author}</span>,
    },
    {
      key: "publishedAt",
      header: t("admin.content.colPublished", { defaultValue: "Published" }),
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
      header: t("admin.content.colUpdated", { defaultValue: "Updated" }),
      sortable: true,
      sortAccessor: (c) => c.updatedAt,
      cell: (c) => (
        <span className="text-sm text-muted-foreground">{c.updatedAt}</span>
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
      <div className="flex items-center justify-between">
        <Badge color="secondary">
          {t("admin.content.itemCount", { defaultValue: items.length === 1 ? "{{count}} {{type}}" : "{{count}} {{type}}s", count: items.length, type: typeLabel })}
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

      <DataTable
        columns={columns}
        data={items}
        rowKey={(c) => c.id}
        loading={isLoading}
        emptyTitle={t("admin.content.noTypeContent", { defaultValue: "No {{type}} content", type: typeLabel.toLowerCase() })}
        emptyDescription={t("admin.content.noTypeContentDesc", { defaultValue: "Create a new {{type}} to get started.", type: typeLabel.toLowerCase() })}
      />

      {deleteTarget && (
        <ConfirmDialog
          open={Boolean(deleteTarget)}
          onOpenChange={(open) => !open && setDeleteTarget(null)}
          title={t("admin.content.deleteContentTitle", { defaultValue: "Delete Content" })}
          description={t("admin.content.deleteContentConfirm", { defaultValue: 'Are you sure you want to delete "{{title}}"? This action cannot be undone.', title: deleteTarget.title })}
          confirmLabel={t("admin.content.delete", { defaultValue: "Delete" })}
          severity="destructive"
          onConfirm={() => deleteMutation.mutate(deleteTarget.id)}
          loading={deleteMutation.isPending}
        />
      )}
    </div>
  );
}
