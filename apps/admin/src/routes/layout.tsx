import { ArrowLeftOutlined, EyeOutlined, HolderOutlined, LayoutOutlined, LoadingOutlined, PlusOutlined, SaveOutlined, DeleteOutlined } from "@ant-design/icons";
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Typography, Button, Card, Select, Badge } from "@/lib/antd";
import { widgetApi, type LayoutWidget, type WidgetDefinition } from "../lib/widget-api";

const PAGES = [
  "index",
  "about",
  "browse",
  "search",
  "guide",
  "downloads",
  "publications",
  "help",
] as const;

type PageName = (typeof PAGES)[number];

// ---------------------------------------------------------------------------
// Sortable widget item
// ---------------------------------------------------------------------------

interface SortableWidgetItemProps {
  item: LayoutWidget;
  widget?: WidgetDefinition;
  onRemove: (name: string) => void;
}

function SortableWidgetItem({ item, widget, onRemove }: SortableWidgetItemProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: item.name });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`flex items-center gap-3 rounded-lg border border-border bg-card p-3 ${
        isDragging ? "opacity-50 shadow-lg" : ""
      }`}
    >
      <button
        type="button"
        {...attributes}
        {...listeners}
        className="cursor-grab touch-none rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground active:cursor-grabbing"
        aria-label="Drag to reorder"
      >
        <HolderOutlined className="size-4" />
      </button>
      <div className="min-w-0 flex-1">
        <p className="font-mono text-sm font-medium">{item.name}</p>
        <p className="truncate text-xs text-muted-foreground">
          {widget?.display_name ?? "Unknown widget"}
        </p>
      </div>
      {widget ? (
        <Badge color="default" className="text-xs">
          {widget.category}
        </Badge>
      ) : null}
      <Button
        type="text"
        size="small"
        className="size-8 p-0 text-destructive hover:text-destructive"
        onClick={() => onRemove(item.name)}
        title="Remove from layout"
        aria-label={`Remove ${item.name} from layout`}
      >
        <DeleteOutlined className="size-3.5" />
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function LayoutEditorPage() {
  const queryClient = useQueryClient();
  const [pageName, setPageName] = useState<PageName>("index");
  const [widgets, setWidgets] = useState<LayoutWidget[]>([]);
  const [baselinePage, setBaselinePage] = useState<PageName | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  // Fetch current layout for selected page
  const {
    data: layout,
    isError: layoutError,
    isFetching: layoutLoading,
    isSuccess: layoutLoaded,
  } = useQuery({
    queryKey: ["admin-layout", pageName],
    queryFn: () => widgetApi.getLayout(pageName),
    enabled: pageName.length > 0,
  });

  // Fetch all widgets for the picker
  const { data: allWidgetsData } = useQuery({
    queryKey: ["admin-widgets", 1, 1000],
    queryFn: () => widgetApi.list({ page: 1, page_size: 200 }),
    placeholderData: { items: [], total: 0 },
  });
  const allWidgets = allWidgetsData?.items ?? [];

  // Sync widgets state with fetched layout
  useEffect(() => {
    if (layoutLoaded && Array.isArray(layout?.widgets)) {
      setWidgets(layout.widgets);
      setBaselinePage(pageName);
    }
  }, [layout, layoutLoaded, pageName]);

  const hasFetchedBaseline = layoutLoaded && Array.isArray(layout?.widgets);
  const hasCurrentBaseline = hasFetchedBaseline && baselinePage === pageName;
  const layoutUnavailable = layoutError || (!layoutLoading && !hasFetchedBaseline);

  const saveMutation = useMutation({
    mutationFn: () => widgetApi.saveLayout(pageName, widgets),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-layout", pageName] });
    },
  });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setWidgets((items) => {
      const oldIndex = items.findIndex((w) => w.name === active.id);
      const newIndex = items.findIndex((w) => w.name === over.id);
      return arrayMove(items, oldIndex, newIndex);
    });
  };

  const handleRemove = (name: string) => {
    setWidgets((items) => items.filter((w) => w.name !== name));
  };

  const handleAdd = (name: string) => {
    if (widgets.some((w) => w.name === name)) return;
    setWidgets((items) => [...items, { name }]);
    setShowAdd(false);
  };

  const availableWidgets = allWidgets.filter(
    (w) => w.is_active && !widgets.some((placed) => placed.name === w.name),
  );

  const widgetMap = new Map(allWidgets.map((w) => [w.name, w]));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/widgets">
            <Button type="text" size="small">
              <ArrowLeftOutlined className="size-4" />
              Widgets
            </Button>
          </Link>
          <div>
            <h2 className="font-serif text-2xl font-semibold">Layout Editor</h2>
            <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
              <LayoutOutlined className="size-3.5" />
              Arrange widgets on pages via drag-and-drop.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/widget-preview">
            <Button type="default" size="small">
              <EyeOutlined className="size-4" />
              Preview
            </Button>
          </Link>
          <Button
            size="small"
            onClick={() => saveMutation.mutate()}
            disabled={!hasCurrentBaseline || layoutLoading || saveMutation.isPending}
          aria-label="Save Layout"
          >
            {saveMutation.isPending ? (
              <LoadingOutlined className="size-4 animate-spin" />
            ) : (
              <SaveOutlined className="size-4" />
            )}
            {saveMutation.isPending ? "Saving…" : "Save Layout"}
          </Button>
        </div>
      </div>

      {saveMutation.isSuccess ? (
        <div className="rounded-lg border border-success/30 bg-success/10 px-4 py-2 text-sm text-success">
          Layout saved successfully.
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Page selector + widget order */}
        <div className="lg:col-span-2">
          <Card>
            <div className="flex flex-row items-center justify-between gap-4">
              <div>
                <Typography.Title level={5}>Page Layout</Typography.Title>
                <Typography.Text type="secondary">
                  Drag widgets to reorder. Use the add button to insert more.
                </Typography.Text>
              </div>
              <div className="w-48">
                <Select
                  value={pageName}
                  onChange={(v) => setPageName(v as PageName)}
                >


                    {PAGES.map((p) => (
                      <Select.Option key={p} value={p}>
                        /{p === "index" ? "" : p}
                      </Select.Option>
                    ))}

                </Select>
              </div>
            </div>
            <div className="space-y-3">
              {layoutLoading || (hasFetchedBaseline && !hasCurrentBaseline) ? (
                <div className="space-y-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="h-14 animate-pulse rounded-lg bg-muted" />
                  ))}
                </div>
              ) : layoutUnavailable ? (
                <div
                  role="alert"
                  className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive"
                >
                  <p className="font-medium">Unable to load the current layout.</p>
                  <p className="mt-1 text-muted-foreground">
                    Saving is disabled until a configuration baseline is available.
                  </p>
                </div>
              ) : (
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragEnd={handleDragEnd}
                >
                  <SortableContext
                    items={widgets.map((w) => w.name)}
                    strategy={verticalListSortingStrategy}
                  >
                    <div className="space-y-2">
                      {widgets.length === 0 ? (
                        <div className="rounded-lg border border-dashed border-border p-8 text-center">
                          <p className="text-sm text-muted-foreground">
                            No widgets on this page. Add one below.
                          </p>
                        </div>
                      ) : (
                        widgets.map((w) => (
                          <SortableWidgetItem
                            key={w.name}
                            item={w}
                            widget={widgetMap.get(w.name)}
                            onRemove={handleRemove}
                          />
                        ))
                      )}
                    </div>
                  </SortableContext>
                </DndContext>
              )}

              <div className="pt-2">
                {showAdd ? (
                  <Card className="border-dashed">
                    <div className="space-y-2 p-3">
                      <p className="text-xs font-medium text-muted-foreground">
                        Select a widget to add:
                      </p>
                      <div className="max-h-64 space-y-1 overflow-y-auto">
                        {availableWidgets.length === 0 ? (
                          <p className="py-4 text-center text-sm text-muted-foreground">
                            All active widgets are already on this page.
                          </p>
                        ) : (
                          availableWidgets.map((w) => (
                            <button
                              key={w.name}
                              type="button"
                              onClick={() => handleAdd(w.name)}
                              className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
                            >
                              <span>
                                <span className="font-mono">{w.name}</span>
                                <span className="ml-2 text-xs text-muted-foreground">
                                  {w.display_name}
                                </span>
                              </span>
                              <Badge color="default" className="text-xs">
                                {w.category}
                              </Badge>
                            </button>
                          ))
                        )}
                      </div>
                      <Button
                        type="text"
                        size="small"
                        onClick={() => setShowAdd(false)}
                      >
                        Cancel
                      </Button>
                    </div>
                  </Card>
                ) : (
                  <Button
                    type="default"
                    size="small"
                    className="w-full"
                    onClick={() => setShowAdd(true)}
                  >
                    <PlusOutlined className="size-4" />
                    Add Widget
                  </Button>
                )}
              </div>
            </div>
          </Card>
        </div>

        {/* Info sidebar */}
        <div>
          <Card>
            <div>
              <Typography.Title level={5}>About</Typography.Title>
            </div>
            <div className="space-y-3 text-sm text-muted-foreground">
              <p>
                Widgets are rendered in the order listed. Drag the handle to
                reorder; use the trash icon to remove a widget from the layout
                (widget definition is not deleted).
              </p>
              <p>
                Changes are saved when you click <strong>Save Layout</strong>.
                Unsaved changes are lost if you navigate away.
              </p>
              <div className="rounded-md bg-muted p-3">
                <p className="text-xs font-medium text-foreground">Page: /{pageName === "index" ? "" : pageName}</p>
                <p className="mt-1 text-xs">{widgets.length} widget(s) placed</p>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
