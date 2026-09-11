import { AppstoreOutlined, EyeOutlined, EditOutlined, PlusOutlined, DeleteOutlined, RiseOutlined, LayoutOutlined } from "@ant-design/icons";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { Badge, Button, Card, Typography } from "@/lib/antd";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { ConfirmDialog } from "../components/confirm-dialog";
import { widgetApi, type WidgetDefinition } from "../lib/widget-api";
import { useTranslation } from "react-i18next";

const CATEGORY_LABEL_KEYS: Record<string, string> = {
  hero: "categoryHero",
  navigation: "categoryNavigation",
  search: "categorySearch",
  data_table: "categoryDataTable",
  detail: "categoryDetail",
  visualization: "categoryVisualization",
  stats: "categoryStats",
  external: "categoryExternal",
  layout: "categoryLayout",
  custom: "categoryCustom",
};

const WIDGET_CATEGORIES: Record<string, string> = {
  hero: "Hero",
  navigation: "Navigation",
  search: "Search",
  data_table: "Data Table",
  detail: "Detail",
  visualization: "Visualization",
  stats: "Stats",
  external: "External",
  layout: "Layout",
  custom: "Custom",
};

function categoryBadgeColor(category: string): string {
  switch (category) {
    case "stats": return "blue";
    case "visualization": return "green";
    case "data_table": return "gold";
    case "search": return "cyan";
    default: return "default";
  }
}

function permissionBadge(perm: string): string {
  switch (perm) {
    case "public": return "blue";
    case "authenticated": return "gold";
    case "admin": return "red";
    default: return "default";
  }
}

export default function WidgetsPage() {
  const { t } = useTranslation();
  const categoryLabel = (c: string) => {
    const key = CATEGORY_LABEL_KEYS[c];
    return key ? t(`admin.ops.${key}`, { defaultValue: WIDGET_CATEGORIES[c] ?? c }) : c;
  };
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [deleteTarget, setDeleteTarget] = useState<WidgetDefinition | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["admin-widgets", page],
    queryFn: () => widgetApi.list({ page, page_size: 20 }),
    placeholderData: { items: [], total: 0 },
  });

  const deleteMutation = useMutation({
    mutationFn: (name: string) => widgetApi.remove(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-widgets"] });
      setDeleteTarget(null);
    },
  });

  const widgets = data?.items ?? [];

  const columns: DataTableColumn<WidgetDefinition>[] = [
    {
      key: "name",
      header: t("admin.ops.name", { defaultValue: "Name" }),
      sortable: true,
      sortAccessor: (w) => w.name,
      cell: (w) => (
        <div className="min-w-0">
          <p className="font-mono text-sm font-medium">{w.name}</p>
          <p className="truncate text-xs text-muted-foreground">{w.display_name}</p>
        </div>
      ),
    },
    {
      key: "category",
      header: t("admin.news.columns.category", { defaultValue: "Category" }),
      sortable: true,
      sortAccessor: (w) => w.category,
      cell: (w) => (
        <Badge color={categoryBadgeColor(w.category)}>
          {categoryLabel(w.category)}
        </Badge>
      ),
    },
    {
      key: "permissions",
      header: t("admin.ops.permissions", { defaultValue: "Permissions" }),
      sortable: true,
      sortAccessor: (w) => w.permissions,
      cell: (w) => (
        <Badge color={permissionBadge(w.permissions)}>{w.permissions}</Badge>
      ),
    },
    {
      key: "cache_ttl",
      header: t("admin.ops.cacheTtl", { defaultValue: "Cache TTL" }),
      sortable: true,
      sortAccessor: (w) => w.cache_ttl,
      align: "right",
      cell: (w) => (
        <span className="font-mono text-sm text-muted-foreground">
          {w.cache_ttl > 0 ? `${w.cache_ttl}s` : "—"}
        </span>
      ),
    },
    {
      key: "is_active",
      header: t("admin.news.columns.status", { defaultValue: "Status" }),
      sortable: true,
      sortAccessor: (w) => (w.is_active ? 1 : 0),
      cell: (w) =>
        w.is_active ? (
          <Badge color="success">{t("admin.ops.active", { defaultValue: "Active" })}</Badge>
        ) : (
          <Badge >{t("admin.ops.inactive", { defaultValue: "Inactive" })}</Badge>
        ),
    },
    {
      key: "actions",
      header: t("admin.news.columns.actions", { defaultValue: "Actions" }),
      align: "right",
      cell: (w) => (
        <div className="flex items-center justify-end gap-1">
          <Link to="/widget-preview" search={{ name: w.name }}>
            <Button
              type="text"
              size="small"
              className="size-8 p-0"
              title={t("admin.news.actions.preview", { defaultValue: "Preview" })}
              aria-label={t("admin.ops.previewWidgetAria", { name: w.display_name, defaultValue: "Preview widget {{name}}" })}
            >
              <EyeOutlined className="size-3.5" />
            </Button>
          </Link>
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => navigate({ to: "/widgets/$name", params: { name: w.name } })}
            title={t("admin.news.actions.edit", { defaultValue: "Edit" })}
            aria-label={t("admin.ops.editWidgetAria", { name: w.display_name, defaultValue: "Edit widget {{name}}" })}
          >
            <EditOutlined className="size-3.5" />
          </Button>
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => setDeleteTarget(w)}
            title={t("admin.news.actions.delete", { defaultValue: "Delete" })}
            aria-label={t("admin.ops.deleteWidgetAria", { name: w.display_name, defaultValue: "Delete widget {{name}}" })}
          >
            <DeleteOutlined className="size-3.5 text-destructive" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Typography.Title level={2}>{t("admin.ops.widgetManagerTitle", { defaultValue: "Widget Manager" })}</Typography.Title>
          <Typography.Text type="secondary">{t("admin.ops.widgetManagerSubtitle", { defaultValue: "Create, edit, and manage reusable UI widgets across the site." })}</Typography.Text>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/widget-health"><Button size="small" icon={<RiseOutlined />}>{t("admin.ops.health", { defaultValue: "Health" })}</Button></Link>
          <Link to="/layout"><Button size="small" icon={<LayoutOutlined />}>{t("admin.ops.layoutEditor", { defaultValue: "Layout Editor" })}</Button></Link>
          <Link to="/widgets/$name" params={{ name: "new" }}><Button type="primary" size="small" icon={<PlusOutlined />}>{t("admin.ops.newWidget", { defaultValue: "New Widget" })}</Button></Link>
        </div>
      </div>

      <Card>

          <Typography.Title level={5}>
            <AppstoreOutlined className="size-4 text-primary" />
            {t("admin.ops.allWidgets", { defaultValue: "All Widgets" })}
          </Typography.Title>


          <p className="text-sm text-muted-foreground">
            {t("admin.ops.widgetsIntro", { defaultValue: "Widgets are reusable UI components that can be placed on pages via the layout editor. Each widget has a template, data source, and optional parameter schema." })}
          </p>

      </Card>

      <DataTable
        columns={columns}
        data={widgets}
        rowKey={(w) => w.name}
        loading={isLoading}
        page={page}
        pageSize={20}
        total={data?.total ?? 0}
        onPageChange={setPage}
        onRowClick={(w) =>
          navigate({ to: "/widgets/$name", params: { name: w.name } })
        }
        emptyTitle={t("admin.ops.noWidgets", { defaultValue: "No widgets defined" })}
        emptyDescription={t("admin.ops.noWidgetsDesc", { defaultValue: "Create your first widget to start building page layouts." })}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title={t("admin.ops.deleteWidgetTitle", { defaultValue: "Delete widget" })}
        description={t("admin.ops.deleteWidgetConfirm", { name: deleteTarget?.display_name ?? "", defaultValue: "Are you sure you want to delete the widget \"{{name}}\"? This will remove it from all page layouts." })}
        confirmLabel={t("admin.news.actions.delete", { defaultValue: "Delete" })}
        severity="destructive"
        loading={deleteMutation.isPending}
        onConfirm={() => {
          if (deleteTarget) deleteMutation.mutate(deleteTarget.name);
        }}
      />
    </div>
  );
}
