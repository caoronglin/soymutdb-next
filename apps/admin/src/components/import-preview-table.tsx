import * as React from "react";

export type ImportPreviewRow = Record<string, unknown>;

export interface ImportPreviewPatch {
  row_key: string;
  column_name: string;
  old_value: unknown | null;
  new_value: string;
  patch_type: "set";
}

interface EditingCell {
  id: number;
  rowIndex: number;
  rowKey: string;
  columnName: string;
  value: string;
}

export interface ImportPreviewTableProps {
  columns: readonly string[];
  rows: readonly ImportPreviewRow[];
  rowKey: (row: ImportPreviewRow, index: number) => string;
  editable?: boolean;
  onPatchesChange?: (patches: ImportPreviewPatch[]) => void;
  maxPatches?: number;
  height?: number;
  rowHeight?: number;
  overscan?: number;
  ariaLabel?: string;
  className?: string;
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function flattenPatches(
  patchesByRow: Map<string, Map<string, ImportPreviewPatch>>,
): ImportPreviewPatch[] {
  const patches: ImportPreviewPatch[] = [];
  for (const patchesForRow of patchesByRow.values()) {
    for (const patch of patchesForRow.values()) patches.push(patch);
  }
  return patches;
}

interface PreviewRowProps {
  columns: readonly string[];
  row: ImportPreviewRow;
  rowIndex: number;
  rowKey: string;
  rowHeight: number;
  editable: boolean;
  editing: EditingCell | null;
  patchRevision: number;
  patchesByRow: Map<string, Map<string, ImportPreviewPatch>>;
  onBeginEdit: (rowIndex: number, columnName: string) => void;
  onEditValueChange: (value: string) => void;
  onCommitEdit: () => void;
  onCancelEdit: () => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
}

const PreviewRow = React.memo(function PreviewRow({
  columns,
  row,
  rowIndex,
  rowKey,
  rowHeight,
  editable,
  editing,
  patchRevision: _patchRevision,
  patchesByRow,
  onBeginEdit,
  onEditValueChange,
  onCommitEdit,
  onCancelEdit,
  inputRef,
}: PreviewRowProps) {
  const rowPatches = patchesByRow.get(rowKey);

  return (
    <div
      role="row"
      aria-rowindex={rowIndex + 2}
      data-import-preview-row
      className="grid border-b border-border bg-card"
      style={{
        gridTemplateColumns: `repeat(${columns.length}, minmax(10rem, 1fr))`,
        height: rowHeight,
      }}
    >
      {columns.map((columnName, columnIndex) => {
        const patch = rowPatches?.get(columnName);
        const value = patch ? displayValue(patch.new_value) : displayValue(row[columnName]);
        const isEditing =
          editing?.rowKey === rowKey && editing.columnName === columnName;
        const label = `Edit ${columnName} for row ${rowKey}`;

        return (
          <div
            key={columnName}
            role="gridcell"
            aria-colindex={columnIndex + 1}
            aria-label={isEditing ? label : `${columnName} ${value}`}
            aria-readonly={!editable}
            data-testid={`import-preview-cell-${rowIndex}-${columnName}`}
            tabIndex={editable ? 0 : -1}
            className="min-w-0 border-r border-border px-3 py-2 text-sm outline-none last:border-r-0 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
            onDoubleClick={() => onBeginEdit(rowIndex, columnName)}
            onKeyDown={(event) => {
              if (!editable || isEditing) return;
              if (event.key === "Enter" || event.key === "F2") {
                event.preventDefault();
                onBeginEdit(rowIndex, columnName);
              }
            }}
          >
            {isEditing ? (
              <input
                ref={inputRef}
                aria-label={label}
                className="h-6 w-full rounded border border-input bg-background px-1 text-sm outline-none focus:ring-2 focus:ring-ring"
                value={editing.value}
                onChange={(event) => onEditValueChange(event.target.value)}
                onBlur={onCommitEdit}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    onCommitEdit();
                  } else if (event.key === "Escape") {
                    event.preventDefault();
                    onCancelEdit();
                  }
                }}
              />
            ) : (
              <span className="block truncate" title={value}>
                {value || "—"}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
});

/**
 * A fixed-row-height import preview grid that renders only its visible window.
 * It deliberately keeps source rows in props, while edits live in a bounded
 * sparse patch map; no complete editable copy of the data is created.
 */
export function ImportPreviewTable({
  columns,
  rows,
  rowKey,
  editable = false,
  onPatchesChange,
  maxPatches = 10_000,
  height = 360,
  rowHeight = 36,
  overscan = 1,
  ariaLabel = "Import preview",
  className,
}: ImportPreviewTableProps) {
  const [windowStart, setWindowStart] = React.useState(0);
  const [editing, setEditing] = React.useState<EditingCell | null>(null);
  const [patchRevision, setPatchRevision] = React.useState(0);
  const [editError, setEditError] = React.useState<string | null>(null);
  const [patchesByRow] = React.useState(
    () => new Map<string, Map<string, ImportPreviewPatch>>(),
  );
  const patchCountRef = React.useRef(0);
  const scrollTopRef = React.useRef(0);
  const editSequenceRef = React.useRef(0);
  const committedEditRef = React.useRef<number | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const visibleRowCount = Math.max(1, Math.ceil(height / rowHeight));
  const resolvedWindowStart = Math.min(
    windowStart,
    Math.max(0, rows.length - visibleRowCount),
  );
  const windowEnd = Math.min(
    rows.length,
    resolvedWindowStart + visibleRowCount + overscan * 2,
  );
  const visibleRows = React.useMemo(() => {
    const start = Math.max(0, resolvedWindowStart - overscan);
    const result: Array<{ row: ImportPreviewRow; index: number; key: string }> = [];
    for (let index = start; index < windowEnd; index += 1) {
      const row = rows[index];
      if (row) result.push({ row, index, key: rowKey(row, index) });
    }
    return result;
  }, [overscan, resolvedWindowStart, rowKey, rows, windowEnd]);

  React.useEffect(() => {
    inputRef.current?.focus();
  }, [editing]);

  const emitPatches = React.useCallback(() => {
    onPatchesChange?.(flattenPatches(patchesByRow));
  }, [onPatchesChange, patchesByRow]);

  const beginEdit = React.useCallback(
    (rowIndex: number, columnName: string) => {
      if (!editable) return;
      const row = rows[rowIndex];
      if (!row) return;
      const key = rowKey(row, rowIndex);
      const existingPatch = patchesByRow.get(key)?.get(columnName);
      if (!existingPatch && patchCountRef.current >= maxPatches) {
        setEditError(`Maximum of ${maxPatches} pending edits reached.`);
        return;
      }
      const id = editSequenceRef.current + 1;
      editSequenceRef.current = id;
      committedEditRef.current = null;
      setEditError(null);
      setEditing({
        id,
        rowIndex,
        rowKey: key,
        columnName,
        value: displayValue(existingPatch?.new_value ?? row[columnName]),
      });
    },
    [editable, maxPatches, patchesByRow, rowKey, rows],
  );

  const changeEditValue = React.useCallback((value: string) => {
    setEditing((current) => (current ? { ...current, value } : current));
  }, []);

  const cancelEdit = React.useCallback(() => {
    setEditing(null);
  }, []);

  const commitEdit = React.useCallback(() => {
    if (!editing || committedEditRef.current === editing.id) return;
    committedEditRef.current = editing.id;
    const row = rows[editing.rowIndex];
    if (!row) {
      setEditing(null);
      return;
    }
    const originalValue = row[editing.columnName] ?? null;
    const originalText = displayValue(originalValue);
    const patchesForRow = patchesByRow.get(editing.rowKey) ?? new Map();
    const existingPatch = patchesForRow.get(editing.columnName);
    if (editing.value === originalText) {
      if (patchesForRow.delete(editing.columnName)) patchCountRef.current -= 1;
      if (patchesForRow.size === 0) patchesByRow.delete(editing.rowKey);
    } else {
      if (!existingPatch) patchCountRef.current += 1;
      patchesForRow.set(editing.columnName, {
        row_key: editing.rowKey,
        column_name: editing.columnName,
        old_value: originalValue,
        new_value: editing.value,
        patch_type: "set",
      });
      patchesByRow.set(editing.rowKey, patchesForRow);
    }
    setEditing(null);
    setPatchRevision((revision) => revision + 1);
    emitPatches();
  }, [editing, emitPatches, patchesByRow, rows]);

  return (
    <div className={className}>
      <div
        role="row"
        className="grid border-b border-border bg-muted/50 text-xs font-medium uppercase tracking-wide text-muted-foreground"
        style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(10rem, 1fr))` }}
      >
        {columns.map((columnName, index) => (
          <div key={columnName} role="columnheader" aria-colindex={index + 1} className="border-r border-border px-3 py-2 last:border-r-0">
            {columnName}
          </div>
        ))}
      </div>
      <div
        role="grid"
        aria-label={ariaLabel}
        aria-rowcount={rows.length + 1}
        aria-colcount={columns.length}
        className="overflow-auto rounded-b-md border border-t-0 border-border bg-card"
        style={{ height }}
        onScroll={(event) => {
          scrollTopRef.current = event.currentTarget.scrollTop;
          const nextStart = Math.floor(scrollTopRef.current / rowHeight);
          setWindowStart((current) => (current === nextStart ? current : nextStart));
        }}
      >
        <div style={{ height: rows.length * rowHeight, position: "relative" }}>
          <div
            role="rowgroup"
            style={{
              position: "absolute",
              top: Math.max(0, resolvedWindowStart - overscan) * rowHeight,
              left: 0,
              right: 0,
            }}
          >
            {visibleRows.map(({ row, index, key }) => (
              <PreviewRow
                key={key}
                columns={columns}
                row={row}
                rowIndex={index}
                rowKey={key}
                rowHeight={rowHeight}
                editable={editable}
                editing={editing}
                patchRevision={patchRevision}
                patchesByRow={patchesByRow}
                onBeginEdit={beginEdit}
                onEditValueChange={changeEditValue}
                onCommitEdit={commitEdit}
                onCancelEdit={cancelEdit}
                inputRef={inputRef}
              />
            ))}
          </div>
        </div>
      </div>
      {editError ? <p role="alert" className="mt-2 text-sm text-destructive">{editError}</p> : null}
    </div>
  );
}

export default ImportPreviewTable;
