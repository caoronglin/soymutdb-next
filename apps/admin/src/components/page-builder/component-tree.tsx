/** Nested sortable Page Builder tree backed by the registry layout contract. */
import { DeleteOutlined, HolderOutlined } from "@ant-design/icons";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useTranslation } from "react-i18next";
import { Badge, Button } from "@/lib/antd";
import { cn } from "../../lib/cn";
import type { ComponentDescriptor, PageComponentNode } from "@soymutdb/shared";

export interface SelectionPath { path: number[]; }

interface ComponentTreeProps {
  root: PageComponentNode;
  descriptors: Map<string, ComponentDescriptor>;
  selectedPath: SelectionPath | null;
  onSelect: (path: SelectionPath) => void;
  onRemoveNode: (path: SelectionPath) => void;
  /** Move active node either beside another node or into a layout container. */
  onMove: (from: number[], over: number[]) => void;
}

function nodeId(path: number[]): string { return path.join("."); }

function SortableNode({ node, path, depth, descriptors, selectedKey, onSelect, onRemove }: {
  node: PageComponentNode;
  path: number[];
  depth: number;
  descriptors: Map<string, ComponentDescriptor>;
  selectedKey: string | null;
  onSelect: (path: SelectionPath) => void;
  onRemove: (path: SelectionPath) => void;
}) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: nodeId(path) });
  const descriptor = descriptors.get(node.type);
  const isContainer = descriptor?.is_layout_container === true;
  const children = isContainer ? node.children ?? [] : [];
  const label = descriptor?.label ?? node.type;
  const selected = selectedKey === nodeId(path);

  return <div ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} className={isDragging ? "opacity-50" : ""}>
    <div
      className={cn("flex items-center gap-2 rounded-md border px-2 py-2", selected ? "border-primary bg-primary/10" : "border-border bg-card hover:bg-accent")}
      style={{ marginLeft: depth * 16 }} onClick={() => onSelect({ path })} role="button" tabIndex={0}
      onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onSelect({ path }); }}
    >
      <button type="button" {...attributes} {...listeners} className="cursor-grab touch-none text-muted-foreground hover:text-foreground" aria-label={t("admin.builder.dragToReorder", { defaultValue: "Drag to reorder" })}>
        <HolderOutlined className="size-4" />
      </button>
      <Badge className="font-mono text-xs" color="default">{node.type}</Badge>
      <span className="min-w-0 flex-1 truncate text-sm">{label}</span>
      {isContainer ? <span className="text-xs text-muted-foreground">{t("admin.builder.dropTarget", { defaultValue: "Drop target" })}</span> : null}
      <Button type="text" size="small" danger className="size-7 p-0" onClick={(event) => { event.stopPropagation(); onRemove({ path }); }} aria-label={t("admin.builder.removeComponent", { defaultValue: "Remove component" })}>
        <DeleteOutlined className="size-3.5" />
      </Button>
    </div>
    {isContainer ? <SortableContext items={children.map((_child, index) => nodeId([...path, index]))} strategy={verticalListSortingStrategy}>
      <div className="space-y-1.5 py-1.5">
        {children.length === 0 ? <div className="ml-4 rounded-md border border-dashed p-2 text-xs text-muted-foreground">{t("admin.builder.emptyContainer", { defaultValue: "Drop a component here" })}</div> : null}
        {children.map((child, index) => <SortableNode key={nodeId([...path, index])} node={child} path={[...path, index]} depth={depth + 1} descriptors={descriptors} selectedKey={selectedKey} onSelect={onSelect} onRemove={onRemove} />)}
      </div>
    </SortableContext> : null}
  </div>;
}

export function ComponentTree({ root, descriptors, selectedPath, onSelect, onRemoveNode, onMove }: ComponentTreeProps) {
  const { t } = useTranslation();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const children = root.children ?? [];
  const selectedKey = selectedPath ? nodeId(selectedPath.path) : null;
  const handleDragEnd = (event: DragEndEvent) => {
    if (!event.over || event.active.id === event.over.id) return;
    const from = String(event.active.id).split(".").map(Number);
    const over = String(event.over.id).split(".").map(Number);
    if (from.some(Number.isNaN) || over.some(Number.isNaN)) return;
    onMove(from, over);
  };
  return <div className="space-y-2">
    <div className="text-sm font-medium text-muted-foreground">{t("admin.builder.root", { defaultValue: "Root" })}</div>
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={children.map((_child, index) => nodeId([index]))} strategy={verticalListSortingStrategy}>
        <div className="space-y-1.5">
          {children.length === 0 ? <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">{t("admin.builder.noComponents", { defaultValue: "No components yet. Add one from the palette." })}</div> : null}
          {children.map((child, index) => <SortableNode key={nodeId([index])} node={child} path={[index]} depth={0} descriptors={descriptors} selectedKey={selectedKey} onSelect={onSelect} onRemove={onRemoveNode} />)}
        </div>
      </SortableContext>
    </DndContext>
  </div>;
}

export default ComponentTree;
