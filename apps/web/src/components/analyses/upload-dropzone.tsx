/**
 * UploadDropzone — drag & drop / click-to-select file input for analysis
 * pipelines, shared by the fastp and scanpy submission pages.
 *
 * Validates extension whitelist, per-file size ceiling (500 MB) and file
 * count locally; invalid selections are rejected with a toast and the
 * file list is left untouched.
 */

import * as React from "react";
import { UploadCloud, X, File as FileIcon, FileWarning } from "lucide-react";
import { cn, useToast, Badge } from "@soymutdb/ui";

export interface UploadDropzoneProps {
  /** Accepted extensions (lowercase, leading dot) — e.g. [".fq", ".fq.gz"]. */
  extensions: readonly string[];
  /** Human label for the accepted format — e.g. "FASTQ". */
  formatLabel: string;
  /** Maximum number of files (1 for scanpy, 2 for paired-end fastp). */
  maxFiles: number;
  /** Per-file size ceiling in bytes (default 500 MB). */
  maxSizeBytes?: number;
  /** Currently selected files (controlled). */
  files: readonly File[];
  /** Called with a valid new selection (previous selection replaced). */
  onFilesChange: (files: File[]) => void;
  /** True while an upload is in progress — blocks further selection. */
  disabled?: boolean;
  /** Paired-end hint (fastp): shows "R1 / R2" guidance when maxFiles === 2. */
  pairedHint?: boolean;
  className?: string;
}

export const ANALYSIS_MAX_SIZE_BYTES = 500 * 1024 * 1024;

function matchesExtension(name: string, extensions: readonly string[]): boolean {
  const lower = name.toLowerCase();
  return extensions.some((ext) => lower.endsWith(ext));
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

export function UploadDropzone({
  extensions,
  formatLabel,
  maxFiles,
  maxSizeBytes = ANALYSIS_MAX_SIZE_BYTES,
  files,
  onFilesChange,
  disabled = false,
  pairedHint = false,
  className,
}: UploadDropzoneProps) {
  const { error: toastError } = useToast();
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = React.useState(false);
  const dragDepth = React.useRef(0);

  const validateAndSet = React.useCallback(
    (incoming: File[]) => {
      const list = Array.from(incoming);
      if (list.length === 0) return;
      if (list.length > maxFiles) {
        toastError(
          `Too many files`,
          `${formatLabel} jobs accept at most ${maxFiles} file${maxFiles > 1 ? "s" : ""} (got ${list.length}).`,
        );
        return;
      }
      const bad = list.find((f) => !matchesExtension(f.name, extensions));
      if (bad) {
        toastError(
          `Unsupported file: ${bad.name}`,
          `Expected ${formatLabel} files (${extensions.join(", ")})`,
        );
        return;
      }
      const oversized = list.find((f) => f.size > maxSizeBytes);
      if (oversized) {
        toastError(
          `File too large: ${oversized.name}`,
          `${formatBytes(oversized.size)} exceeds the ${formatBytes(maxSizeBytes)} limit.`,
        );
        return;
      }
      onFilesChange(list);
    },
    [extensions, formatLabel, maxFiles, maxSizeBytes, onFilesChange, toastError],
  );

  const onDrop = React.useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      dragDepth.current = 0;
      setDragging(false);
      if (disabled) return;
      validateAndSet(Array.from(e.dataTransfer.files));
    },
    [disabled, validateAndSet],
  );

  return (
    <div className={cn("grid gap-3", className)}>
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-label={`Upload ${formatLabel} file${maxFiles > 1 ? "s" : ""}`}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (!disabled && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          if (disabled) return;
          dragDepth.current += 1;
          setDragging(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (dragDepth.current === 0) setDragging(false);
        }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-10 text-center outline-none transition-colors",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          dragging
            ? "border-primary bg-primary/5"
            : "border-border bg-muted/20 hover:border-primary/50 hover:bg-muted/30",
          disabled && "pointer-events-none cursor-not-allowed opacity-60",
        )}
      >
        <UploadCloud className={cn("size-8", dragging ? "text-primary" : "text-muted-foreground")} aria-hidden />
        <div>
          <p className="text-sm font-medium text-foreground">
            Drag &amp; drop {formatLabel} file{maxFiles > 1 ? "s" : ""} here
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            or click to browse · {extensions.join(" / ")} · max {formatBytes(maxSizeBytes)} per file
            {maxFiles > 1 ? ` · up to ${maxFiles} files` : ""}
          </p>
          {pairedHint && maxFiles === 2 ? (
            <p className="mt-1 text-xs text-muted-foreground/80">
              Paired-end: select R1 and R2 together (order: R1 first, R2 second)
            </p>
          ) : null}
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple={maxFiles > 1}
          accept={extensions.join(",")}
          disabled={disabled}
          className="sr-only"
          onChange={(e) => {
            validateAndSet(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
      </div>

      {files.length > 0 ? (
        <ul className="grid gap-2">
          {files.map((f, i) => (
            <li
              key={`${f.name}-${i}`}
              className="flex items-center gap-3 rounded-lg border bg-card px-3 py-2"
            >
              <FileIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{f.name}</p>
                <p className="text-xs text-muted-foreground">{formatBytes(f.size)}</p>
              </div>
              {maxFiles === 2 ? (
                <Badge variant="secondary" className="text-[10px] uppercase">
                  {i === 0 ? "R1" : "R2"}
                </Badge>
              ) : null}
              <button
                type="button"
                aria-label={`Remove ${f.name}`}
                disabled={disabled}
                onClick={() => onFilesChange(files.filter((_, fi) => fi !== i))}
                className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="size-4" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <FileWarning className="size-3.5" aria-hidden />
          No file selected yet.
        </p>
      )}
    </div>
  );
}
