/**
 * Multi-dimensional data workspace for the console.
 *
 * The conceptual model is borrowed from NocoBase: one data source, many saved
 * views over it, and each view is a presentation (grid / kanban / gallery)
 * with its own visible fields, filters, sort and grouping. Unlike a generic
 * low-code runtime, the sources are fixed and release-scoped: every row comes
 * from the same public read APIs the portal uses, so a view cannot bypass
 * release visibility or expose an internal identifier.
 */
import * as React from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Drawer,
  Empty,
  Input,
  InputNumber,
  PageContainer,
  Pagination,
  ProCard,
  ProTable,
  Select,
  Skeleton,
  Space,
  Switch,
  Tag,
  type ProColumns,
} from "@/lib/antd";
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  StarOutlined,
} from "@ant-design/icons";
import {
  DATA_VIEW_KINDS,
  DATA_VIEW_SOURCES,
  createAdminDataView,
  deleteAdminDataView,
  fetchDataViewRows,
  listAdminDataViews,
  listDataViewSources,
  updateAdminDataView,
  type AdminDataView,
  type AdminDataViewInput,
  type AdminDataViewPatch,
  type DataViewKind,
  type DataViewRowPage,
  type DataViewSortDir,
  type DataViewSource,
  type DataViewSourceInfo,
} from "@soymutdb/api-client";
import { ConfirmDialog } from "../components/confirm-dialog";

type Row = Record<string, unknown>;

interface DraftView {
  name: string;
  view_type: DataViewKind;
  visible_fields: string[];
  filter_rows: Array<{ key: string; value: string }>;
  sort_field: string | null;
  sort_dir: DataViewSortDir | null;
  group_field: string | null;
  title_field: string | null;
  page_size: number;
  is_default: boolean;
  notes: string;
}

const IDENTITY_FIELD: Record<DataViewSource, string> = {
  genes: "gene_id",
  variants: "variant_id",
  mutant_lines: "public_id",
};

const SEGMENTED_FIELD_LIMIT = 4;

function rowKey(source: DataViewSource, row: Row, index: number): string {
  return String(row[IDENTITY_FIELD[source]] ?? index);
}

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function draftFromSource(info: DataViewSourceInfo | undefined): DraftView {
  return {
    name: "",
    view_type: "grid",
    visible_fields: [...(info?.default_fields ?? [])].slice(0, 8),
    filter_rows: [],
    sort_field: null,
    sort_dir: null,
    group_field: null,
    title_field: null,
    page_size: 25,
    is_default: false,
    notes: "",
  };
}

function draftFromView(view: AdminDataView): DraftView {
  return {
    name: view.name,
    view_type: view.view_type,
    visible_fields: [...view.visible_fields],
    filter_rows: Object.entries(view.filters).map(([key, value]) => ({ key, value })),
    sort_field: view.sort_field,
    sort_dir: view.sort_dir,
    group_field: view.group_field,
    title_field: view.title_field,
    page_size: view.page_size,
    is_default: view.is_default,
    notes: view.notes ?? "",
  };
}

/** Turn the drawer's rows into the strict filter object, dropping blanks. */
function draftFilters(draft: DraftView): Record<string, string> {
  const filters: Record<string, string> = {};
  for (const row of draft.filter_rows) {
    if (!row.key || !row.value.trim()) continue;
    filters[row.key] = row.value.trim();
  }
  return filters;
}

function draftIssue(draft: DraftView): string | null {
  if (!draft.name.trim()) return "name";
  if (draft.visible_fields.length === 0) return "fields";
  if (draft.view_type === "kanban" && !draft.group_field) return "group";
  if (draft.sort_dir && !draft.sort_field) return "sort";
  return null;
}

export default function DataViewsPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [source, setSource] = React.useState<DataViewSource>("genes");
  const [activeViewId, setActiveViewId] = React.useState<number | null>(null);
  const [renderOverride, setRenderOverride] = React.useState<
    { viewId: number; mode: DataViewKind } | null
  >(null);
  const [page, setPage] = React.useState(1);
  const [editor, setEditor] = React.useState<
    { mode: "create" | "edit"; viewId: number | null; draft: DraftView } | null
  >(null);
  const [deleteTarget, setDeleteTarget] = React.useState<AdminDataView | null>(null);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [saveError, setSaveError] = React.useState<string | null>(null);

  const sourcesQuery = useQuery({
    queryKey: ["admin", "data-views", "sources"],
    queryFn: listDataViewSources,
    staleTime: Infinity,
  });
  const viewsQuery = useQuery({
    queryKey: ["admin", "data-views", source],
    queryFn: () => listAdminDataViews({ source }),
    staleTime: 15_000,
  });

  const views = React.useMemo(() => viewsQuery.data?.items ?? [], [viewsQuery.data]);
  const sourceInfo = sourcesQuery.data?.items.find((item) => item.source === source);

  const activeView = React.useMemo(() => {
    const selected = views.find((view) => view.id === activeViewId);
    if (selected) return selected;
    return views.find((view) => view.is_default) ?? views[0] ?? null;
  }, [views, activeViewId]);

  // A saved view carries its own render mode; the selector previews another
  // mode without mutating the saved configuration.
  const renderMode: DataViewKind =
    activeView && renderOverride?.viewId === activeView.id
      ? renderOverride.mode
      : activeView?.view_type ?? "grid";

  React.useEffect(() => {
    setPage(1);
  }, [activeView?.id]);

  const gridQuery = useQuery({
    queryKey: ["admin", "data-views", "rows", activeView?.id, activeView?.updated_at, page],
    queryFn: () => fetchDataViewRows(activeView as AdminDataView, { page }),
    enabled: Boolean(activeView) && activeView?.source !== "variants",
    staleTime: 15_000,
  });

  const variantQuery = useInfiniteQuery({
    queryKey: ["admin", "data-views", "rows", activeView?.id, activeView?.updated_at, "cursor"],
    queryFn: ({ pageParam }) =>
      fetchDataViewRows(activeView as AdminDataView, { cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last: DataViewRowPage) =>
      last.hasMore ? last.nextCursor : undefined,
    enabled: Boolean(activeView) && activeView?.source === "variants",
    staleTime: 15_000,
  });

  const rows: Row[] = React.useMemo(() => {
    if (!activeView) return [];
    if (activeView.source === "variants") {
      return variantQuery.data?.pages.flatMap((item) => item.items) ?? [];
    }
    return gridQuery.data?.items ?? [];
  }, [activeView, gridQuery.data, variantQuery.data]);

  const loading = activeView?.source === "variants" ? variantQuery.isLoading : gridQuery.isLoading;
  const rowsError = activeView?.source === "variants" ? variantQuery.isError : gridQuery.isError;
  const hasMore =
    activeView?.source === "variants"
      ? Boolean(variantQuery.hasNextPage)
      : Boolean(gridQuery.data?.hasMore);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "data-views"] });
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!editor) throw new Error("no draft");
      const { draft } = editor;
      const payload = {
        name: draft.name.trim(),
        view_type: draft.view_type,
        visible_fields: draft.visible_fields,
        filters: draftFilters(draft),
        sort_field: draft.sort_field,
        sort_dir: draft.sort_dir,
        group_field: draft.group_field,
        title_field: draft.title_field,
        page_size: draft.page_size,
        is_default: draft.is_default,
        notes: draft.notes.trim() || null,
      };
      if (editor.mode === "edit" && editor.viewId) {
        const patch: AdminDataViewPatch = payload;
        return updateAdminDataView(editor.viewId, patch);
      }
      const input: AdminDataViewInput = { ...payload, source };
      return createAdminDataView(input);
    },
    onSuccess: (view) => {
      message.success(t("common.success"));
      setSaveError(null);
      setEditor(null);
      setActiveViewId(view.id);
      setSource(view.source);
      invalidate();
    },
    onError: (error) => {
      setSaveError(error instanceof Error ? error.message : String(error));
      message.error(t("common.error"));
    },
  });

  const promoteMutation = useMutation({
    mutationFn: (view: AdminDataView) => updateAdminDataView(view.id, { is_default: true }),
    onSuccess: (view) => {
      message.success(t("common.success"));
      setActiveViewId(view.id);
      invalidate();
    },
    onError: (error) => message.error(error instanceof Error ? error.message : t("common.error")),
  });

  const deleteMutation = useMutation({
    mutationFn: (view: AdminDataView) => deleteAdminDataView(view.id),
    onSuccess: () => {
      message.success(t("common.success"));
      setDeleteTarget(null);
      setDeleteError(null);
      setActiveViewId(null);
      invalidate();
    },
    onError: (error) => {
      setDeleteError(error instanceof Error ? error.message : String(error));
      message.error(t("common.error"));
    },
  });

  const startCreate = () => {
    setSaveError(null);
    setEditor({
      mode: "create",
      viewId: null,
      draft: draftFromSource(sourceInfo),
    });
  };

  const startEdit = (view: AdminDataView) => {
    setSaveError(null);
    setEditor({ mode: "edit", viewId: view.id, draft: draftFromView(view) });
  };

  const patchDraft = (patch: Partial<DraftView>) => {
    setEditor((previous) =>
      previous ? { ...previous, draft: { ...previous.draft, ...patch } } : previous,
    );
  };

  const fieldOptions = (sourceInfo?.fields ?? []).map((field) => ({
    value: field,
    label: <code>{field}</code>,
  }));
  const filterOptions = (sourceInfo?.filter_fields ?? []).map((field) => ({
    value: field,
    label: <code>{field}</code>,
  }));

  const columns: ProColumns<Row>[] = (activeView?.visible_fields ?? []).map((field) => ({
    title: <code>{field}</code>,
    dataIndex: field,
    key: field,
    render: (value) => cellText(value),
  }));

  const viewColumns: ProColumns<AdminDataView>[] = [
    {
      title: t("admin.dataViews.name"),
      dataIndex: "name",
      key: "name",
      render: (name, row) => (
        <Space>
          <Button type="link" size="small" onClick={() => setActiveViewId(row.id)}>
            {String(name)}
          </Button>
          {row.is_default ? <Tag color="green">{t("admin.dataViews.defaultTag")}</Tag> : null}
        </Space>
      ),
    },
    {
      title: t("admin.dataViews.viewTypeLabel"),
      key: "view_type",
      render: (_, row) => <Tag>{t(`admin.dataViews.viewType.${row.view_type}`)}</Tag>,
    },
    {
      title: t("admin.dataViews.fieldsLabel"),
      key: "fields",
      render: (_, row) => <span className="font-mono text-xs">{row.visible_fields.join(", ")}</span>,
    },
    {
      title: t("common.edit"),
      key: "actions",
      render: (_, row) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => startEdit(row)}>
            {t("common.edit")}
          </Button>
          {row.is_default ? null : (
            <Button
              size="small"
              icon={<StarOutlined />}
              loading={promoteMutation.isPending}
              onClick={() => promoteMutation.mutate(row)}
            >
              {t("admin.dataViews.setDefault")}
            </Button>
          )}
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => {
              setDeleteError(null);
              setDeleteTarget(row);
            }}
          >
            {t("common.delete")}
          </Button>
        </Space>
      ),
    },
  ];

  const groupField = activeView?.group_field;
  const titleField = activeView?.title_field ?? IDENTITY_FIELD[source];

  function renderGrid() {
    if (!activeView) return <Empty description={t("admin.dataViews.noActiveView")} />;
    return (
      <>
        <div data-testid="data-views-grid">
          <ProTable<Row>
            rowKey={IDENTITY_FIELD[activeView.source]}
            size="small"
            dataSource={rows}
            pagination={false}
            columns={columns}
          />
        </div>
        {activeView.source === "genes" ? (
          <Pagination
            current={page}
            pageSize={activeView.page_size}
            total={gridQuery.data?.total ?? 0}
            onChange={setPage}
            data-testid="data-views-pagination"
          />
        ) : null}
        {hasMore || page > 1 ? (
          <Space>
            {page > 1 ? (
              <Button onClick={() => setPage((current) => Math.max(1, current - 1))}>
                {t("common.previous")}
              </Button>
            ) : null}
            {activeView.source === "variants" ? (
              <Button
                onClick={() => void variantQuery.fetchNextPage()}
                loading={variantQuery.isFetchingNextPage}
                disabled={!variantQuery.hasNextPage}
              >
                {t("admin.dataViews.loadMore")}
              </Button>
            ) : (
              <Button disabled={!hasMore} onClick={() => setPage((current) => current + 1)}>
                {t("common.next")}
              </Button>
            )}
          </Space>
        ) : null}
      </>
    );
  }

  function renderKanban() {
    if (!activeView) return <Empty description={t("admin.dataViews.noActiveView")} />;
    if (!groupField) {
      return (
        <Alert
          type="warning"
          showIcon
          title={t("admin.dataViews.groupRequiredTitle")}
          description={t("admin.dataViews.groupRequired")}
        />
      );
    }
    const groups = new Map<string, Row[]>();
    for (const row of rows) {
      const key = cellText(row[groupField]);
      groups.set(key, [...(groups.get(key) ?? []), row]);
    }
    if (groups.size === 0) return <Empty description={t("common.noData")} />;
    return (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4" data-testid="data-views-kanban">
        {[...groups.entries()].map(([group, groupRows]) => (
          <div key={group} className="rounded-lg border border-border/60 bg-card p-3">
            <div className="mb-2 flex items-center justify-between">
              <strong>{group}</strong>
              <Tag>{groupRows.length}</Tag>
            </div>
            <Space direction="vertical">
              {groupRows.map((row, index) => (
                <div key={rowKey(activeView.source, row, index)} className="rounded border border-border/50 p-2">
                  <div className="font-medium">{cellText(row[titleField])}</div>
                  <div className="text-xs text-muted-foreground">
                    {activeView.visible_fields
                      .filter((field) => field !== titleField)
                      .slice(0, SEGMENTED_FIELD_LIMIT)
                      .map((field) => `${field}: ${cellText(row[field])}`)
                      .join(" · ")}
                  </div>
                </div>
              ))}
            </Space>
          </div>
        ))}
      </div>
    );
  }

  function renderGallery() {
    if (!activeView) return <Empty description={t("admin.dataViews.noActiveView")} />;
    if (rows.length === 0) return <Empty description={t("common.noData")} />;
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="data-views-gallery">
        {rows.map((row, index) => (
          <Card key={rowKey(activeView.source, row, index)} size="small">
            <div className="mb-2 font-medium">{cellText(row[titleField])}</div>
            <dl className="space-y-1 text-sm">
              {activeView.visible_fields.map((field) => (
                <div key={field} className="flex justify-between gap-4">
                  <dt className="font-mono text-xs text-muted-foreground">{field}</dt>
                  <dd className="text-right">{cellText(row[field])}</dd>
                </div>
              ))}
            </dl>
          </Card>
        ))}
      </div>
    );
  }

  const issue = editor ? draftIssue(editor.draft) : null;

  return (
    <PageContainer title={t("admin.dataViews.title")} subTitle={t("admin.dataViews.subtitle")}>
      <div className="space-y-6">
        <Alert type="info" showIcon title={t("admin.dataViews.bannerTitle")} description={t("admin.dataViews.bannerDescription")} />

        <ProCard>
          <Space wrap>
            <Select
              value={source}
              aria-label={t("admin.dataViews.sourceLabel")}
              style={{ width: 220 }}
              options={DATA_VIEW_SOURCES.map((value) => ({
                value,
                label: t(`admin.dataViews.source.${value}`),
              }))}
              onChange={(value: DataViewSource) => {
                setSource(value);
                setActiveViewId(null);
                setPage(1);
              }}
            />
            <Select
              value={renderMode}
              aria-label={t("admin.dataViews.viewTypeLabel")}
              style={{ width: 180 }}
              options={DATA_VIEW_KINDS.map((value) => ({
                value,
                label: t(`admin.dataViews.viewType.${value}`),
              }))}
              onChange={(value: DataViewKind) => {
                if (activeView) setRenderOverride({ viewId: activeView.id, mode: value });
              }}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={startCreate}>
              {t("admin.dataViews.newView")}
            </Button>
          </Space>
        </ProCard>

        <ProCard size="small" title={t("admin.dataViews.savedViews")}>
          {viewsQuery.isLoading ? (
            <Skeleton active />
          ) : viewsQuery.isError ? (
            <div role="alert" data-testid="data-views-list-error" className="text-sm text-destructive">
              {t("admin.dataViews.loadError")}
            </div>
          ) : views.length === 0 ? (
            <Empty description={t("admin.dataViews.empty")} />
          ) : (
            <ProTable<AdminDataView>
              rowKey="id"
              size="small"
              dataSource={views}
              pagination={false}
              columns={viewColumns}
            />
          )}
        </ProCard>

        <ProCard
          size="small"
          title={
            activeView
              ? t("admin.dataViews.activeView", { name: activeView.name })
              : t("admin.dataViews.preview")
          }
          extra={
            activeView ? (
              <Button size="small" icon={<EditOutlined />} onClick={() => startEdit(activeView)}>
                {t("common.edit")}
              </Button>
            ) : null
          }
        >
          {loading ? (
            <Skeleton active />
          ) : rowsError ? (
            <div role="alert" data-testid="data-views-rows-error" className="text-sm text-destructive">
              {t("admin.dataViews.rowsError")}
            </div>
          ) : !activeView ? (
            <Empty description={t("admin.dataViews.noActiveView")} />
          ) : renderMode === "kanban" ? (
            renderKanban()
          ) : renderMode === "gallery" ? (
            renderGallery()
          ) : (
            renderGrid()
          )}
        </ProCard>
      </div>

      <Drawer
        open={Boolean(editor)}
        width={560}
        title={t(editor?.mode === "edit" ? "admin.dataViews.editView" : "admin.dataViews.newView")}
        onClose={() => setEditor(null)}
        data-testid="data-views-editor"
      >
        {editor ? (
          <div className="space-y-4">
            <Tag>{t(`admin.dataViews.source.${source}`)}</Tag>
            <label className="block text-sm">
              {t("admin.dataViews.name")}
              <Input
                value={editor.draft.name}
                placeholder={t("admin.dataViews.namePlaceholder")}
                onChange={(event) => patchDraft({ name: event.target.value })}
                data-testid="data-views-name"
              />
            </label>

            <label className="block text-sm">
              {t("admin.dataViews.viewTypeLabel")}
              <Select
                value={editor.draft.view_type}
                aria-label={t("admin.dataViews.viewTypeLabel")}
                options={DATA_VIEW_KINDS.map((value) => ({
                  value,
                  label: t(`admin.dataViews.viewType.${value}`),
                }))}
                onChange={(value: DataViewKind) => patchDraft({ view_type: value })}
                data-testid="data-views-view-type"
              />
            </label>

            <div className="text-sm">
              {t("admin.dataViews.fieldsLabel")}
              <p className="text-xs text-muted-foreground">{t("admin.dataViews.fieldsHint")}</p>
              <div className="grid gap-1 sm:grid-cols-2">
                {fieldOptions.map((option) => {
                  const position = editor.draft.visible_fields.indexOf(option.value);
                  return (
                    <Space key={option.value} size={6}>
                      <Checkbox
                        checked={position >= 0}
                        aria-label={option.value}
                        onChange={(event) => {
                          const fields = event.target.checked
                            ? [...editor.draft.visible_fields, option.value]
                            : editor.draft.visible_fields.filter((field) => field !== option.value);
                          patchDraft({ visible_fields: fields });
                        }}
                      />
                      {option.label}
                      {position >= 0 ? <Tag>{position + 1}</Tag> : null}
                      {position > 0 ? (
                        <Button
                          size="small"
                          type="text"
                          aria-label={`${option.value} up`}
                          onClick={() => {
                            const fields = [...editor.draft.visible_fields];
                            [fields[position - 1], fields[position]] = [fields[position], fields[position - 1]];
                            patchDraft({ visible_fields: fields });
                          }}
                        >
                          ↑
                        </Button>
                      ) : null}
                      {position >= 0 && position < editor.draft.visible_fields.length - 1 ? (
                        <Button
                          size="small"
                          type="text"
                          aria-label={`${option.value} down`}
                          onClick={() => {
                            const fields = [...editor.draft.visible_fields];
                            [fields[position + 1], fields[position]] = [fields[position], fields[position + 1]];
                            patchDraft({ visible_fields: fields });
                          }}
                        >
                          ↓
                        </Button>
                      ) : null}
                    </Space>
                  );
                })}
              </div>
            </div>

            <div className="text-sm">
              {t("admin.dataViews.filtersLabel")}
              <Space direction="vertical">
                {editor.draft.filter_rows.map((row, index) => (
                  <Space key={index}>
                    <Select
                      value={row.key}
                      aria-label={t("admin.dataViews.filterKey")}
                      options={filterOptions}
                      onChange={(value: string) =>
                        patchDraft({
                          filter_rows: editor.draft.filter_rows.map((item, position) =>
                            position === index ? { ...item, key: value } : item,
                          ),
                        })
                      }
                    />
                    <Input
                      value={row.value}
                      aria-label={t("admin.dataViews.filterValue")}
                      placeholder={t("admin.dataViews.filterValue")}
                      onChange={(event) =>
                        patchDraft({
                          filter_rows: editor.draft.filter_rows.map((item, position) =>
                            position === index ? { ...item, value: event.target.value } : item,
                          ),
                        })
                      }
                    />
                    <Button
                      size="small"
                      type="text"
                      danger
                      aria-label={t("admin.dataViews.removeFilter")}
                      onClick={() =>
                        patchDraft({
                          filter_rows: editor.draft.filter_rows.filter((_, position) => position !== index),
                        })
                      }
                    >
                      ×
                    </Button>
                  </Space>
                ))}
                <Button
                  size="small"
                  onClick={() =>
                    patchDraft({
                      filter_rows: [
                        ...editor.draft.filter_rows,
                        { key: sourceInfo?.filter_fields[0] ?? "", value: "" },
                      ],
                    })
                  }
                >
                  + {t("admin.dataViews.addFilter")}
                </Button>
              </Space>
            </div>

            <Space wrap>
              <label className="block text-sm">
                {t("admin.dataViews.sortField")}
                <Select
                  value={editor.draft.sort_field ?? ""}
                  aria-label={t("admin.dataViews.sortField")}
                  options={[{ value: "", label: t("admin.dataViews.none") }, ...fieldOptions]}
                  onChange={(value: string) =>
                    patchDraft({ sort_field: value || null, sort_dir: value ? editor.draft.sort_dir ?? "asc" : null })
                  }
                />
              </label>
              <label className="block text-sm">
                {t("admin.dataViews.sortDirection")}
                <Select
                  value={editor.draft.sort_dir ?? ""}
                  aria-label={t("admin.dataViews.sortDirection")}
                  options={[
                    { value: "", label: t("admin.dataViews.none") },
                    { value: "asc", label: t("admin.dataViews.asc") },
                    { value: "desc", label: t("admin.dataViews.desc") },
                  ]}
                  onChange={(value: string) =>
                    patchDraft({ sort_dir: (value || null) as DataViewSortDir | null })
                  }
                />
              </label>
            </Space>

            <Space wrap>
              <label className="block text-sm">
                {t("admin.dataViews.groupField")}
                <Select
                  value={editor.draft.group_field ?? ""}
                  aria-label={t("admin.dataViews.groupField")}
                  options={[{ value: "", label: t("admin.dataViews.none") }, ...fieldOptions]}
                  onChange={(value: string) => patchDraft({ group_field: value || null })}
                />
              </label>
              <label className="block text-sm">
                {t("admin.dataViews.titleField")}
                <Select
                  value={editor.draft.title_field ?? ""}
                  aria-label={t("admin.dataViews.titleField")}
                  options={[{ value: "", label: t("admin.dataViews.none") }, ...fieldOptions]}
                  onChange={(value: string) => patchDraft({ title_field: value || null })}
                />
              </label>
            </Space>

            <Space wrap>
              <label className="block text-sm">
                {t("admin.dataViews.pageSize")}
                <InputNumber
                  value={editor.draft.page_size}
                  min={5}
                  max={200}
                  onChange={(value) => {
                    const next = typeof value === "number" ? value : 25;
                    patchDraft({ page_size: next });
                  }}
                />
              </label>
              <label className="block text-sm">
                {t("admin.dataViews.defaultTag")}
                <Switch
                  checked={editor.draft.is_default}
                  aria-label={t("admin.dataViews.defaultTag")}
                  onChange={(checked) => patchDraft({ is_default: checked })}
                />
              </label>
            </Space>

            <label className="block text-sm">
              {t("admin.dataViews.notes")}
              <Input.TextArea
                value={editor.draft.notes}
                onChange={(event) => patchDraft({ notes: event.target.value })}
              />
            </label>

            {issue ? (
              <Alert
                type="warning"
                showIcon
                title={t(`admin.dataViews.issue.${issue}`)}
                data-testid="data-views-draft-issue"
              />
            ) : null}
            {saveError ? (
              <div role="alert" data-testid="data-views-save-error" className="text-sm text-destructive">
                {t("common.errorReason", {
                  reason: saveError,
                  defaultValue: "Server response: {{reason}}",
                })}
              </div>
            ) : null}

            <Space>
              <Button
                type="primary"
                loading={saveMutation.isPending}
                disabled={Boolean(issue)}
                onClick={() => saveMutation.mutate()}
              >
                {t("common.save")}
              </Button>
              <Button onClick={() => setEditor(null)}>{t("common.cancel")}</Button>
            </Space>
          </div>
        ) : null}
      </Drawer>

      {deleteTarget ? (
        <ConfirmDialog
          open={Boolean(deleteTarget)}
          onOpenChange={(open) => {
            if (!open) {
              setDeleteTarget(null);
              setDeleteError(null);
            }
          }}
          title={t("admin.dataViews.deleteTitle")}
          description={t("admin.dataViews.deleteConfirm", { name: deleteTarget.name })}
          confirmLabel={t("common.delete")}
          severity="destructive"
          onConfirm={() => deleteMutation.mutate(deleteTarget)}
          loading={deleteMutation.isPending}
          error={
            deleteError ? (
              <span data-testid="data-views-delete-error">
                {t("common.errorReason", {
                  reason: deleteError,
                  defaultValue: "Server response: {{reason}}",
                })}
              </span>
            ) : null
          }
        />
      ) : null}
    </PageContainer>
  );
}