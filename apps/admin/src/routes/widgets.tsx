import { AppstoreOutlined, EyeOutlined, EditOutlined, PlusOutlined, DeleteOutlined, RiseOutlined, LayoutOutlined } from "@ant-design/icons";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { Badge, Button, Card, Typography } from "@/lib/antd";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { ConfirmDialog } from "../components/confirm-dialog";
import { widgetApi, type WidgetDefinition } from "../lib/widget-api";

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
      header: "Name",
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
      header: "Category",
      sortable: true,
      sortAccessor: (w) => w.category,
      cell: (w) => (
        <Badge color={categoryBadgeColor(w.category)}>
          {WIDGET_CATEGORIES[w.category] ?? w.category}
        </Badge>
      ),
    },
    {
      key: "permissions",
      header: "Permissions",
      sortable: true,
      sortAccessor: (w) => w.permissions,
      cell: (w) => (
        <Badge color={permissionBadge(w.permissions)}>{w.permissions}</Badge>
      ),
    },
    {
      key: "cache_ttl",
      header: "Cache TTL",
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
      header: "Status",
      sortable: true,
      sortAccessor: (w) => (w.is_active ? 1 : 0),
      cell: (w) =>
        w.is_active ? (
          <Badge color="success">Active</Badge>
        ) : (
          <Badge >Inactive</Badge>
        ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: (w) => (
        <div className="flex items-center justify-end gap-1">
          <Link to="/widget-preview" search={{ name: w.name }}>
            <Button
              type="text"
              size="small"
              className="size-8 p-0"
              title="Preview"
              aria-label={`Preview widget ${w.display_name}`}
            >
              <EyeOutlined className="size-3.5" />
            </Button>
          </Link>
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => navigate({ to: "/widgets/$name", params: { name: w.name } })}
            title="Edit"
            aria-label={`Edit widget ${w.display_name}`}
          >
            <EditOutlined className="size-3.5" />
          </Button>
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => setDeleteTarget(w)}
            title="Delete"
            aria-label={`Delete widget ${w.display_name}`}
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
          <Typography.Title level={2}>Widget Manager</Typography.Title>
          <Typography.Text type="secondary">Create, edit, and manage reusable UI widgets across the site.</Typography.Text>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/widget-health"><Button size="small" icon={<RiseOutlined />}>Health</Button></Link>
          <Link to="/layout"><Button size="small" icon={<LayoutOutlined />}>Layout Editor</Button></Link>
          <Link to="/widgets/$name" params={{ name: "new" }}><Button type="primary" size="small" icon={<PlusOutlined />}>New Widget</Button></Link>
        </div>
      </div>

      <Card>

          <Typography.Title level={5}>
            <AppstoreOutlined className="size-4 text-primary" />
            All Widgets
          </Typography.Title>


          <p className="text-sm text-muted-foreground">
            Widgets are reusable UI components that can be placed on pages via the
            layout editor. Each widget has a template, data source, and optional
            parameter schema.
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
        emptyTitle="No widgets defined"
        emptyDescription="Create your first widget to start building page layouts."
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title="Delete widget"
        description={`Are you sure you want to delete the widget "${deleteTarget?.display_name}"? This will remove it from all page layouts.`}
        confirmLabel="Delete"
        severity="destructive"
        loading={deleteMutation.isPending}
        onConfirm={() => {
          if (deleteTarget) deleteMutation.mutate(deleteTarget.name);
        }}
      />
    </div>
  );
}
