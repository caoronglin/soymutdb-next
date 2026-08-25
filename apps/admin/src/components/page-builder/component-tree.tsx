/**
 * Ordered component tree with drag-to-reorder (dnd-kit) and node selection.
 *
 * The tree mirrors the ``PageDefinition.root`` shape: a single root component
 * with optional nested ``children`` arrays (only layout containers nest).
 */

import { HolderOutlined, DeleteOutlined } from "@ant-design/icons";
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
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { cn } from "../../lib/cn";
import { Badge, Button } from "@/lib/antd";
import type { ComponentDescriptor, PageComponentNode } from "@soymutdb/shared";

export interface SelectionPath {
  /** Indices from the root down to the selected node. */
  path: number[];
}

interface ComponentTreeProps {
  root: PageComponentNode;
  descriptors: Map<string, ComponentDescriptor>;
  selectedPath: SelectionPath | null;
  onSelect: (path: SelectionPath) => void;
  onRemoveNode: (path: SelectionPath) => void;
  onReorder: (parentChildren: PageComponentNode[], from: number, to: number) => void;
}

function nodeId(path: number[]): string {
  return path.join(".");
}

function NodeRow({
  node,
  depth,
  label,
  selected,
  onSelect,
  onRemove,
  dragHandle,
}: {
  node: PageComponentNode;
  depth: number;
  label: string;
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
  dragHandle: Record<string, unknown>;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md border px-2 py-2",
        selected
          ? "border-primary bg-primary/10"
          : "border-border bg-card hover:bg-accent",
      )}
      style={{ marginLeft: depth * 16 }}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
    >
      <button
        type="button"
        {...dragHandle}
        className="cursor-grab touch-none text-muted-foreground hover:text-foreground"
        aria-label="Drag to reorder"
      >
        <HolderOutlined className="size-4" />
      </button>
      <Badge className="font-mono text-xs" color="default">
        {node.type}
      </Badge>
      <span className="min-w-0 flex-1 truncate text-sm">{label}</span>
      <Button
        type="text"
        size="small"
        danger
        className="size-7 p-0"
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        aria-label="Remove component"
      >
        <DeleteOutlined className="size-3.5" />
      </Button>
    </div>
  );
}

function SortableNode({
  node,
  path,
  depth,
  label,
  selected,
  onSelect,
  onRemove,
}: {
  node: PageComponentNode;
  path: number[];
  depth: number;
  label: string;
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: nodeId(path) });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={isDragging ? "opacity-50" : ""}
    >
      <NodeRow
        node={node}
        depth={depth}
        label={label}
        selected={selected}
        onSelect={onSelect}
        onRemove={onRemove}
        dragHandle={{ ...attributes, ...listeners }}
      />
    </div>
  );
}

export function ComponentTree({
  root,
  descriptors,
  selectedPath,
  onSelect,
  onRemoveNode,
  onReorder,
}: ComponentTreeProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const children = root.children ?? [];
  const selectedKey = selectedPath ? nodeId(selectedPath.path) : null;

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const from = children.findIndex((c, i) => nodeId([i]) === active.id);
    const to = children.findIndex((c, i) => nodeId([i]) === over.id);
    if (from < 0 || to < 0) return;
    onReorder(children, from, to);
  };

  return (
    <div className="space-y-2">
      <div className="text-sm font-medium text-muted-foreground">Root</div>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={children.map((_c, i) => nodeId([i]))}
          strategy={verticalListSortingStrategy}
        >
          <div className="space-y-1.5">
            {children.length === 0 ? (
              <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
                No components yet. Add one from the palette.
              </div>
            ) : (
              children.map((child, i) => {
                const label = descriptors.get(child.type)?.label ?? child.type;
                const path = [i];
                return (
                  <SortableNode
                    key={nodeId(path)}
                    node={child}
                    path={path}
                    depth={0}
                    label={label}
                    selected={selectedKey === nodeId(path)}
                    onSelect={() => onSelect({ path })}
                    onRemove={() => onRemoveNode({ path })}
                  />
                );
              })
            )}
          </div>
        </SortableContext>
      </DndContext>
    </div>
  );
}

export default ComponentTree;
