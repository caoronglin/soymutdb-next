/**
 * Data views: one saved view, one table.
 *
 * A saved view stores presentation only — which fields a table shows, which of
 * those the search box matches, the filters, the sort and the page size. Rows
 * always come from the release-scoped public read APIs, so no view can widen
 * visibility to unreleased records or internal identifiers.
 *
 * The table is the page and the table is the field configuration. Each column
 * header carries two switches (`可搜索` / `展示`) and a drag handle; toggling one
 * issues a single partial `PUT /admin/data-views/{id}` (`{"searchable_fields":
 * [...]}` or `{"visible_fields": [...]}`), applies it optimistically, and rolls
 * the cached view back if the server rejects it. There is no per-toggle save
 * button because the endpoint accepts partial updates (`AdminDataViewUpdate`,
 * `model_dump(exclude_unset=True)`); the drawer is reserved for the settings a
 * table header cannot express (name, filters, sort, grouping, page size,
 * visibility, notes).
 *
 * `view_type` stays a stored value of the view, but this console presents every
 * view as a table. A view saved as a board or a gallery gets one line of copy
 * saying so instead of being silently reinterpreted.
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
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  Alert,
  App,
  Button,
  Drawer,
  Empty,
  Input,
  InputNumber,
  PageContainer,
  Pagination,
  ProTable,
  Select,
  Skeleton,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
  type ProColumns,
} from "@/lib/antd";
import {
  DeleteOutlined,
  HolderOutlined,
  PlusOutlined,
  SettingOutlined,
  StarOutlined,
} from "@ant-design/icons";
import {
  DATA_VIEW_KINDS,
  DATA_VIEW_SOURCES,
  DATA_VIEW_VISIBILITIES,
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
  type DataViewVisibility,
} from "@soymutdb/api-client";
import { PRO_LIST_SHELL } from "../components/pro-table-shell";
import { ConfirmDialog } from "../components/confirm-dialog";
import { cn } from "../lib/cn";

type Row = Record<string, unknown>;
type AdminDataViewList = { items: AdminDataView[]; total: number };

/**
 * The editable copy the drawer keeps while an operator types.
 *
 * `visible_fields` and `searchable_fields` are deliberately absent: they are the
 * table's own axes now, and a second editor for them is exactly the duplication
 * this page removed.
 */
interface ViewDraft {
  name: string;
  view_type: DataViewKind;
  visibility: DataViewVisibility;
  filter_rows: Array<{ key: string; value: string }>;
  sort_field: string | null;
  sort_dir: DataViewSortDir | null;
  group_field: string | null;
  title_field: string | null;
  page_size: number;
  is_default: boolean;
  notes: string;
}

/** The field that identifies a row of each source; also the default card title. */
const ROW_IDENTITY_FIELD: Record<DataViewSource, string> = {
  genes: "gene_id",
  variants: "variant_id",
  mutant_lines: "public_id",
};

const DATA_VIEWS_KEY = ["admin", "data-views"] as const;
const DATA_VIEWS_LIST_KEY = ["admin", "data-views", "list"] as const;

function viewsListKey(source: DataViewSource, includeHidden: boolean) {
  return [...DATA_VIEWS_LIST_KEY, source, includeHidden] as const;
}

/**
 * Row identity of the fetched page.
 *
 * It carries only the settings the *request* depends on: filters, sort and page
 * size. Toggling a column therefore never refetches rows that did not change.
 */
function rowsKey(view: AdminDataView | null, page: number | "cursor") {
  return [
    ...DATA_VIEWS_KEY,
    "rows",
    view?.id ?? null,
    view?.filters ?? null,
    view?.sort_field ?? null,
    view?.sort_dir ?? null,
    view?.page_size ?? null,
    page,
  ] as const;
}

function rowIdentityKey(source: DataViewSource, row: Row, index: number): string {
  return String(row[ROW_IDENTITY_FIELD[source]] ?? index);
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Raw text a search term is matched against; a blank cell matches nothing. */
function searchableText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join(" ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function emptyDraft(): ViewDraft {
  return {
    name: "",
    view_type: "grid",
    visibility: "visible",
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

function draftFromView(view: AdminDataView): ViewDraft {
  return {
    name: view.name,
    view_type: view.view_type,
    visibility: view.visibility,
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

/** Turn the drawer's filter rows into the strict filter object, dropping blanks. */
function draftFilters(draft: ViewDraft): Record<string, string> {
  const filters: Record<string, string> = {};
  for (const row of draft.filter_rows) {
    if (!row.key || !row.value.trim()) continue;
    filters[row.key] = row.value.trim();
  }
  return filters;
}

/** The first reason the draft cannot be saved, as a locale-key suffix. */
function draftIssueKey(draft: ViewDraft): string | null {
  if (!draft.name.trim()) return "name";
  if (draft.view_type === "kanban" && !draft.group_field) return "group";
  if (draft.sort_dir && !draft.sort_field) return "sort";
  return null;
}

/**
 * One column header: drag handle, field name, and the two switches that write
 * this field's presentation back to the saved view.
 *
 * The two switch rows are always rendered at a fixed width, so toggling a switch
 * never reflows the header or the neighbouring columns. The move buttons are the
 * keyboard path for the same reorder the drag handle performs; they stay out of
 * the way until the header is hovered or focused.
 */
function FieldHeader({
  field,
  position,
  count,
  searchable,
  onToggleSearchable,
  onToggleVisible,
  onMove,
}: {
  field: string;
  position: number;
  count: number;
  searchable: boolean;
  onToggleSearchable: (field: string) => void;
  onToggleVisible: (field: string) => void;
  onMove: (field: string, delta: number) => void;
}) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: field,
  });
  const isLastVisible = count <= 1;

  const searchableSwitch = (
    <Switch
      size="small"
      checked={searchable}
      aria-label={t("admin.dataViews.field.searchableAria", { field })}
      data-testid={`field-${field}-searchable`}
      onChange={() => onToggleSearchable(field)}
    />
  );
  const visibleSwitch = (
    <Switch
      size="small"
      checked
      disabled={isLastVisible}
      aria-label={t("admin.dataViews.field.visibleAria", { field })}
      data-testid={`field-${field}-visible`}
      onChange={() => onToggleVisible(field)}
    />
  );

  return (
    <div
      ref={setNodeRef}
      data-testid={`field-header-${field}`}
      className={cn("group/field flex flex-col gap-1 text-xs font-normal", isDragging && "opacity-50")}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      <div className="flex items-center gap-1">
        <button
          type="button"
          {...attributes}
          {...listeners}
          aria-label={t("admin.dataViews.field.dragAria", { field })}
          className="cursor-grab touch-none rounded p-0.5 text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <HolderOutlined aria-hidden />
        </button>
        <span className="min-w-0 flex-1 truncate font-mono" title={field}>
          {field}
        </span>
        <span className="flex shrink-0 items-center opacity-0 transition-opacity group-focus-within/field:opacity-100 group-hover/field:opacity-100">
          <Button
            size="small"
            type="text"
            aria-label={t("admin.dataViews.field.moveLeftAria", { field })}
            disabled={position === 0}
            onClick={() => onMove(field, -1)}
          >
            ‹
          </Button>
          <Button
            size="small"
            type="text"
            aria-label={t("admin.dataViews.field.moveRightAria", { field })}
            disabled={position === count - 1}
            onClick={() => onMove(field, 1)}
          >
            ›
          </Button>
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span className="inline-flex w-[5.25rem] shrink-0 items-center gap-1">
          {searchableSwitch}
          <span className="text-muted-foreground">{t("admin.dataViews.field.searchable")}</span>
        </span>
        <span className="inline-flex w-[4.25rem] shrink-0 items-center gap-1">
          {isLastVisible ? (
            <Tooltip title={t("admin.dataViews.field.lastVisibleHint")}>
              <span className="inline-flex">{visibleSwitch}</span>
            </Tooltip>
          ) : (
            visibleSwitch
          )}
          <span className="text-muted-foreground">{t("admin.dataViews.field.visible")}</span>
        </span>
      </div>
    </div>
  );
}

export default function DataViewsPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [source, setSource] = React.useState<DataViewSource>("genes");
  const [activeViewId, setActiveViewId] = React.useState<number | null>(null);
  const [showHidden, setShowHidden] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [viewEditor, setViewEditor] = React.useState<
    { mode: "create" | "edit"; viewId: number | null; draft: ViewDraft } | null
  >(null);
  const [deleteTarget, setDeleteTarget] = React.useState<AdminDataView | null>(null);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [saveError, setSaveError] = React.useState<string | null>(null);

  const sourcesQuery = useQuery({
    queryKey: [...DATA_VIEWS_KEY, "sources"],
    queryFn: listDataViewSources,
    staleTime: Infinity,
  });
  const viewsQuery = useQuery({
    queryKey: viewsListKey(source, showHidden),
    queryFn: () =>
      listAdminDataViews(showHidden ? { source, includeHidden: true } : { source }),
    staleTime: 15_000,
  });

  const views = React.useMemo(() => viewsQuery.data?.items ?? [], [viewsQuery.data]);
  const sourceInfo = sourcesQuery.data?.items.find((item) => item.source === source);

  const activeView = React.useMemo(() => {
    const selected = views.find((view) => view.id === activeViewId);
    if (selected) return selected;
    return views.find((view) => view.is_default) ?? views[0] ?? null;
  }, [views, activeViewId]);

  React.useEffect(() => {
    setPage(1);
    setSearch("");
  }, [activeView?.id]);

  // Two pagination contracts, two queries: genes and mutant lines page by
  // offset, variants page by cursor. Naming them for the contract keeps a
  // reader from assuming either one is "the grid".
  const pagedRowsQuery = useQuery({
    queryKey: rowsKey(activeView, page),
    queryFn: () => fetchDataViewRows(activeView as AdminDataView, { page }),
    enabled: Boolean(activeView) && activeView?.source !== "variants",
    staleTime: 15_000,
  });

  const cursorRowsQuery = useInfiniteQuery({
    queryKey: rowsKey(activeView, "cursor"),
    queryFn: ({ pageParam }) =>
      fetchDataViewRows(activeView as AdminDataView, { cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last: DataViewRowPage) => (last.hasMore ? last.nextCursor : undefined),
    enabled: Boolean(activeView) && activeView?.source === "variants",
    staleTime: 15_000,
  });

  const rows: Row[] = React.useMemo(() => {
    if (!activeView) return [];
    if (activeView.source === "variants") {
      return cursorRowsQuery.data?.pages.flatMap((item) => item.items) ?? [];
    }
    return pagedRowsQuery.data?.items ?? [];
  }, [activeView, pagedRowsQuery.data, cursorRowsQuery.data]);

  const rowsLoading =
    activeView?.source === "variants" ? cursorRowsQuery.isLoading : pagedRowsQuery.isLoading;
  const rowsError =
    activeView?.source === "variants" ? cursorRowsQuery.isError : pagedRowsQuery.isError;
  const hasMore =
    activeView?.source === "variants"
      ? Boolean(cursorRowsQuery.hasNextPage)
      : Boolean(pagedRowsQuery.data?.hasMore);
  const knownTotal =
    pagedRowsQuery.data?.total ?? cursorRowsQuery.data?.pages[0]?.total ?? null;

  // The search box matches only the fields this view declared searchable. A view
  // with none shows no search box, so "search" is never silently a no-op.
  const searchableFields = React.useMemo(
    () => activeView?.searchable_fields ?? [],
    [activeView],
  );
  const searchTerm = search.trim().toLowerCase();
  const filteredRows: Row[] = React.useMemo(() => {
    if (!searchTerm || searchableFields.length === 0) return rows;
    return rows.filter((row) =>
      searchableFields.some((field) =>
        searchableText(row[field]).toLowerCase().includes(searchTerm),
      ),
    );
  }, [rows, searchTerm, searchableFields]);

  const visibleFields = React.useMemo(() => activeView?.visible_fields ?? [], [activeView]);
  const addableFields = React.useMemo(
    () => (sourceInfo?.fields ?? []).filter((field) => !visibleFields.includes(field)),
    [sourceInfo, visibleFields],
  );

  const invalidateDataViews = () => {
    void queryClient.invalidateQueries({ queryKey: DATA_VIEWS_KEY });
  };

  /**
   * Write a partial view update: one request, applied to the cached list first
   * and undone from the snapshot if the server rejects it.
   */
  const patchViewMutation = useMutation({
    mutationFn: ({ view, patch }: { view: AdminDataView; patch: AdminDataViewPatch }) =>
      updateAdminDataView(view.id, patch),
    onMutate: async ({ view, patch }) => {
      const queryKey = viewsListKey(view.source, showHidden);
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<AdminDataViewList>(queryKey);
      queryClient.setQueryData<AdminDataViewList>(queryKey, (current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.id === view.id ? { ...item, ...patch } : item,
              ),
            }
          : current,
      );
      return { queryKey, previous };
    },
    onError: (error, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(context.queryKey, context.previous);
      }
      message.error(
        t("admin.dataViews.patchFailed", {
          reason: error instanceof Error ? error.message : String(error),
          defaultValue: "Could not save the change: {{reason}}",
        }),
      );
    },
    onSuccess: (updated) => {
      const queryKey = viewsListKey(updated.source, showHidden);
      queryClient.setQueryData<AdminDataViewList>(queryKey, (current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) => (item.id === updated.id ? updated : item)),
            }
          : current,
      );
    },
    onSettled: () => {
      // Only the saved-view list is refetched: the row data does not depend on
      // which fields are displayed or searchable, and refetching it would make
      // every switch cost a public read request.
      void queryClient.invalidateQueries({ queryKey: DATA_VIEWS_LIST_KEY });
    },
  });

  const applyViewPatch = (view: AdminDataView, patch: AdminDataViewPatch) => {
    patchViewMutation.mutate({ view, patch });
  };

  const toggleSearchableField = (field: string) => {
    if (!activeView) return;
    const current = activeView.searchable_fields;
    const next = current.includes(field)
      ? current.filter((item) => item !== field)
      : [...current, field];
    applyViewPatch(activeView, { searchable_fields: next });
  };

  const hideField = (field: string) => {
    if (!activeView) return;
    const current = activeView.visible_fields;
    if (current.length <= 1) return;
    applyViewPatch(activeView, { visible_fields: current.filter((item) => item !== field) });
  };

  const addField = (field: string) => {
    if (!activeView || activeView.visible_fields.includes(field)) return;
    applyViewPatch(activeView, { visible_fields: [...activeView.visible_fields, field] });
  };

  const moveField = (field: string, delta: number) => {
    if (!activeView) return;
    const current = activeView.visible_fields;
    const from = current.indexOf(field);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= current.length) return;
    applyViewPatch(activeView, { visible_fields: arrayMove(current, from, to) });
  };

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id || !activeView) return;
    const current = activeView.visible_fields;
    const from = current.indexOf(String(active.id));
    const to = current.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    applyViewPatch(activeView, { visible_fields: arrayMove(current, from, to) });
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!viewEditor) throw new Error("no draft");
      const { draft } = viewEditor;
      const payload = {
        name: draft.name.trim(),
        view_type: draft.view_type,
        visibility: draft.visibility,
        filters: draftFilters(draft),
        sort_field: draft.sort_field,
        sort_dir: draft.sort_dir,
        group_field: draft.group_field,
        title_field: draft.title_field,
        page_size: draft.page_size,
        is_default: draft.is_default,
        notes: draft.notes.trim() || null,
      };
      if (viewEditor.mode === "edit" && viewEditor.viewId) {
        const patch: AdminDataViewPatch = payload;
        return updateAdminDataView(viewEditor.viewId, patch);
      }
      // A new view starts from the source's default presentation; the operator
      // then tunes the columns in the table header.
      const input: AdminDataViewInput = {
        ...payload,
        source,
        visible_fields: [...(sourceInfo?.default_fields ?? [])],
        searchable_fields: [],
      };
      return createAdminDataView(input);
    },
    onSuccess: (view) => {
      message.success(t("common.success"));
      setSaveError(null);
      setViewEditor(null);
      setActiveViewId(view.id);
      setSource(view.source);
      // A view saved as hidden is filtered out of the list the operator is
      // looking at; keep it on screen rather than dropping it silently.
      if (view.visibility === "hidden") setShowHidden(true);
      invalidateDataViews();
    },
    onError: (error) => {
      setSaveError(error instanceof Error ? error.message : String(error));
      message.error(t("common.error"));
    },
  });

  const setDefaultMutation = useMutation({
    mutationFn: (view: AdminDataView) => updateAdminDataView(view.id, { is_default: true }),
    onSuccess: (view) => {
      message.success(t("common.success"));
      setActiveViewId(view.id);
      invalidateDataViews();
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
      invalidateDataViews();
    },
    onError: (error) => {
      setDeleteError(error instanceof Error ? error.message : String(error));
      message.error(t("common.error"));
    },
  });

  const startCreate = () => {
    setSaveError(null);
    setViewEditor({ mode: "create", viewId: null, draft: emptyDraft() });
  };

  const startEdit = (view: AdminDataView) => {
    setSaveError(null);
    setViewEditor({ mode: "edit", viewId: view.id, draft: draftFromView(view) });
  };

  const patchDraft = (patch: Partial<ViewDraft>) => {
    setViewEditor((previous) =>
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

  const dataColumns: ProColumns<Row>[] = visibleFields.map((field, position) => ({
    title: (
      <FieldHeader
        field={field}
        position={position}
        count={visibleFields.length}
        searchable={searchableFields.includes(field)}
        onToggleSearchable={toggleSearchableField}
        onToggleVisible={hideField}
        onMove={moveField}
      />
    ),
    dataIndex: field,
    key: field,
    render: (value) => {
      const text = formatCell(value);
      return (
        <span className="block truncate" title={text}>
          {text}
        </span>
      );
    },
  }));

  const activeFilters = Object.entries(activeView?.filters ?? {});
  const rowCount = knownTotal ?? filteredRows.length;
  const issueKey = viewEditor ? draftIssueKey(viewEditor.draft) : null;

  function renderRows() {
    if (!activeView) {
      return <Empty description={t("admin.dataViews.noActiveView")} />;
    }
    if (rowsLoading) return <Skeleton active />;
    if (rowsError) {
      return (
        <div role="alert" data-testid="data-views-rows-error" className="text-sm text-destructive">
          {t("admin.dataViews.rowsError")}
        </div>
      );
    }
    return (
      <>
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={visibleFields} strategy={horizontalListSortingStrategy}>
            <ProTable<Row>
              {...PRO_LIST_SHELL}
              // No horizontal scroll: with a fixed layout the columns share the
              // container width and long cells truncate inside their own cell,
              // so the table fits a 1440px viewport instead of pushing the page
              // sideways (PRO_LIST_SHELL's `max-content` default does the latter).
              scroll={{}}
              tableLayout="fixed"
              rowKey={(row, index) => rowIdentityKey(activeView.source, row, index ?? 0)}
              size="small"
              dataSource={filteredRows}
              pagination={false}
              columns={dataColumns}
              locale={{
                emptyText: t(searchTerm ? "admin.dataViews.searchNoMatch" : "common.noData"),
              }}
              data-testid="data-views-table"
            />
          </SortableContext>
        </DndContext>
        <div className="mt-2 flex flex-wrap items-center justify-end gap-2">
          {activeView.source === "genes" ? (
            <Pagination
              current={page}
              pageSize={activeView.page_size}
              total={knownTotal ?? 0}
              onChange={setPage}
              data-testid="data-views-pagination"
            />
          ) : null}
          {activeView.source === "variants" ? (
            cursorRowsQuery.hasNextPage ? (
              <Button
                onClick={() => void cursorRowsQuery.fetchNextPage()}
                loading={cursorRowsQuery.isFetchingNextPage}
              >
                {t("admin.dataViews.loadMore")}
              </Button>
            ) : null
          ) : (
            <Space>
              <Button
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                {t("common.previous")}
              </Button>
              <Button disabled={!hasMore} onClick={() => setPage((current) => current + 1)}>
                {t("common.next")}
              </Button>
            </Space>
          )}
        </div>
      </>
    );
  }

  return (
    <PageContainer
      title={t("admin.dataViews.title")}
      subTitle={t("admin.dataViews.subtitle")}
      extra={[
        <Button
          key="new"
          type="primary"
          icon={<PlusOutlined />}
          // The source catalog supplies the default columns a new view starts
          // from; without it the create request would carry an empty field list,
          // which the API rejects (visible_fields has min_length 1).
          disabled={!sourceInfo}
          data-testid="data-views-new"
          onClick={startCreate}
        >
          {t("admin.dataViews.newView")}
        </Button>,
        <Button
          key="settings"
          icon={<SettingOutlined />}
          disabled={!activeView}
          data-testid="data-views-settings"
          onClick={() => activeView && startEdit(activeView)}
        >
          {t("admin.dataViews.viewSettings")}
        </Button>,
        activeView && !activeView.is_default ? (
          <Button
            key="default"
            icon={<StarOutlined />}
            loading={setDefaultMutation.isPending}
            data-testid="data-views-set-default"
            onClick={() => setDefaultMutation.mutate(activeView)}
          >
            {t("admin.dataViews.setDefault")}
          </Button>
        ) : null,
        <Button
          key="delete"
          danger
          icon={<DeleteOutlined />}
          disabled={!activeView}
          data-testid="data-views-delete"
          onClick={() => {
            if (!activeView) return;
            setDeleteError(null);
            setDeleteTarget(activeView);
          }}
        >
          {t("common.delete")}
        </Button>,
      ]}
    >
      <div className="space-y-3">
        {/* One toolbar row: the view's filters, its field picker and its counts.
            It sits above the table and outside it, so the table is the page. */}
        <div
          className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-3 py-2"
          data-testid="data-views-toolbar"
        >
          <Select
            value={source}
            aria-label={t("admin.dataViews.sourceLabel")}
            style={{ width: 150 }}
            data-testid="data-views-source"
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
            value={activeView ? activeView.id : undefined}
            aria-label={t("admin.dataViews.viewSelect")}
            placeholder={t("admin.dataViews.noActiveView")}
            style={{ minWidth: 200 }}
            data-testid="data-views-view-select"
            options={views.map((view) => ({ value: view.id, label: view.name }))}
            onChange={(value: number) => setActiveViewId(Number(value))}
          />
          {activeView?.is_default ? (
            <Tag color="green">{t("admin.dataViews.defaultTag")}</Tag>
          ) : null}
          {activeView?.visibility === "hidden" ? (
            <Tag color="orange">{t("admin.dataViews.visibility.hidden")}</Tag>
          ) : null}
          {activeView && searchableFields.length > 0 ? (
            <Input
              value={search}
              allowClear
              style={{ width: 200 }}
              aria-label={t("admin.dataViews.searchPlaceholder", {
                fields: searchableFields.join(", "),
              })}
              placeholder={t("admin.dataViews.searchPlaceholder", {
                fields: searchableFields.join(", "),
              })}
              onChange={(event) => setSearch(event.target.value)}
              data-testid="data-views-search"
            />
          ) : null}
          {activeView && addableFields.length > 0 ? (
            <Select
              // Remounted whenever the column set changes: the picker is an
              // action, not a value, so it must fall back to its placeholder
              // after a field has been added.
              key={`add-field-${visibleFields.length}`}
              value={undefined}
              aria-label={t("admin.dataViews.addField", { count: addableFields.length })}
              placeholder={t("admin.dataViews.addField", { count: addableFields.length })}
              style={{ width: 170 }}
              data-testid="data-views-add-field"
              options={addableFields.map((field) => ({ value: field, label: field }))}
              onChange={(value: string) => addField(String(value))}
            />
          ) : null}
          <label className="inline-flex items-center gap-2 text-sm">
            <Switch
              checked={showHidden}
              aria-label={t("admin.dataViews.showHidden")}
              onChange={(checked: boolean) => setShowHidden(checked)}
              data-testid="data-views-show-hidden"
            />
            {t("admin.dataViews.showHidden")}
          </label>
          {activeFilters.length > 0 ? (
            <span className="inline-flex flex-wrap items-center gap-1 text-xs">
              <span className="text-muted-foreground">{t("admin.dataViews.filtersLabel")}</span>
              {activeFilters.map(([key, value]) => (
                <Tag key={key}>
                  <code>{key}</code>={value}
                </Tag>
              ))}
            </span>
          ) : null}
          <span
            className="ml-auto text-xs text-muted-foreground"
            data-testid="data-views-summary"
          >
            {t("admin.dataViews.summary", {
              rows: rowCount,
              columns: visibleFields.length,
              searchable: searchableFields.length,
            })}
            {activeFilters.length > 0
              ? ` · ${t("admin.dataViews.activeFilters", { count: activeFilters.length })}`
              : ""}
          </span>
        </div>

        {viewsQuery.isError ? (
          <div role="alert" data-testid="data-views-list-error" className="text-sm text-destructive">
            {t("admin.dataViews.loadError")}
          </div>
        ) : viewsQuery.isLoading ? (
          <Skeleton active />
        ) : views.length === 0 ? (
          <Empty description={t("admin.dataViews.empty")} />
        ) : (
          <>
            {activeView && activeView.view_type !== "grid" ? (
              <Typography.Text
                type="secondary"
                className="block text-xs"
                data-testid="data-views-layout-note"
              >
                {t(`admin.dataViews.layoutNote.${activeView.view_type}`)}
              </Typography.Text>
            ) : null}
            {renderRows()}
          </>
        )}

      </div>

      <Drawer
        open={Boolean(viewEditor)}
        width={520}
        title={t(viewEditor?.mode === "edit" ? "admin.dataViews.editView" : "admin.dataViews.newView")}
        onClose={() => setViewEditor(null)}
        data-testid="data-views-editor"
      >
        {viewEditor ? (
          <div className="space-y-4">
            <Tag>{t(`admin.dataViews.source.${source}`)}</Tag>
            <label className="block text-sm">
              {t("admin.dataViews.name")}
              <Input
                value={viewEditor.draft.name}
                placeholder={t("admin.dataViews.namePlaceholder")}
                onChange={(event) => patchDraft({ name: event.target.value })}
                data-testid="data-views-name"
              />
            </label>

            <div className="text-sm">
              {t("admin.dataViews.viewTypeLabel")}
              <p className="text-xs text-muted-foreground">{t("admin.dataViews.viewTypeHint")}</p>
              <Select
                value={viewEditor.draft.view_type}
                aria-label={t("admin.dataViews.viewTypeLabel")}
                options={DATA_VIEW_KINDS.map((value) => ({
                  value,
                  label: t(`admin.dataViews.viewType.${value}`),
                }))}
                onChange={(value: DataViewKind) => patchDraft({ view_type: value })}
                data-testid="data-views-view-type"
              />
            </div>

            <div className="text-sm">
              {t("admin.dataViews.visibilityLabel")}
              <p className="text-xs text-muted-foreground">
                {t("admin.dataViews.visibilityHint")}
              </p>
              <Select
                value={viewEditor.draft.visibility}
                aria-label={t("admin.dataViews.visibilityLabel")}
                options={DATA_VIEW_VISIBILITIES.map((value) => ({
                  value,
                  label: t(`admin.dataViews.visibility.${value}`),
                }))}
                onChange={(value: DataViewVisibility) => patchDraft({ visibility: value })}
                data-testid="data-views-visibility"
              />
            </div>

            <div className="text-sm">
              {t("admin.dataViews.filtersLabel")}
              <Space direction="vertical">
                {viewEditor.draft.filter_rows.map((row, index) => (
                  <Space key={index}>
                    <Select
                      value={row.key}
                      aria-label={t("admin.dataViews.filterKey")}
                      options={filterOptions}
                      onChange={(value: string) =>
                        patchDraft({
                          filter_rows: viewEditor.draft.filter_rows.map((item, position) =>
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
                          filter_rows: viewEditor.draft.filter_rows.map((item, position) =>
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
                          filter_rows: viewEditor.draft.filter_rows.filter(
                            (_, position) => position !== index,
                          ),
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
                        ...viewEditor.draft.filter_rows,
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
                  value={viewEditor.draft.sort_field ?? ""}
                  aria-label={t("admin.dataViews.sortField")}
                  options={[{ value: "", label: t("admin.dataViews.none") }, ...fieldOptions]}
                  onChange={(value: string) =>
                    patchDraft({
                      sort_field: value || null,
                      sort_dir: value ? viewEditor.draft.sort_dir ?? "asc" : null,
                    })
                  }
                />
              </label>
              <label className="block text-sm">
                {t("admin.dataViews.sortDirection")}
                <Select
                  value={viewEditor.draft.sort_dir ?? ""}
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
                  value={viewEditor.draft.group_field ?? ""}
                  aria-label={t("admin.dataViews.groupField")}
                  options={[{ value: "", label: t("admin.dataViews.none") }, ...fieldOptions]}
                  onChange={(value: string) => patchDraft({ group_field: value || null })}
                />
              </label>
              <label className="block text-sm">
                {t("admin.dataViews.titleField")}
                <Select
                  value={viewEditor.draft.title_field ?? ""}
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
                  value={viewEditor.draft.page_size}
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
                  checked={viewEditor.draft.is_default}
                  aria-label={t("admin.dataViews.defaultTag")}
                  onChange={(checked) => patchDraft({ is_default: checked })}
                />
              </label>
            </Space>

            <label className="block text-sm">
              {t("admin.dataViews.notes")}
              <Input.TextArea
                value={viewEditor.draft.notes}
                onChange={(event) => patchDraft({ notes: event.target.value })}
              />
            </label>

            {issueKey ? (
              <Alert
                type="warning"
                showIcon
                title={t(`admin.dataViews.issue.${issueKey}`)}
                data-testid="data-views-draft-issue"
              />
            ) : null}
            {saveError ? (
              <div role="alert" data-testid="data-views-save-error" className="text-sm text-destructive">
                {t("admin.dataViews.saveFailed", {
                  reason: saveError,
                  defaultValue: "Could not save the view: {{reason}}",
                })}
              </div>
            ) : null}

            <Space>
              <Button
                type="primary"
                loading={saveMutation.isPending}
                disabled={Boolean(issueKey)}
                onClick={() => saveMutation.mutate()}
              >
                {t("common.save")}
              </Button>
              <Button onClick={() => setViewEditor(null)}>{t("common.cancel")}</Button>
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
                {t("admin.dataViews.saveFailed", {
                  reason: deleteError,
                  defaultValue: "Could not save the view: {{reason}}",
                })}
              </span>
            ) : null
          }
        />
      ) : null}
    </PageContainer>
  );
}