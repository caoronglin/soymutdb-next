import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Upload,
  FileSpreadsheet,
  Database,
  RotateCcw,
  XCircle,
  Loader2,
} from "lucide-react";
import { http } from "@soymutdb/api-client";
import {
  Button,
  Input,
  Badge,
  cn,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@soymutdb/ui";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { StatusBadge, type TaskStatus } from "../components/status-badge";
import { useAuth } from "../lib/auth-context";

// ---------------------------------------------------------------------------
// Types – matches the backend API response shape (snake_case)
// ---------------------------------------------------------------------------

type ImportType =
  | "vcf"
  | "gff3"
  | "fasta"
  | "blast_db"
  | "seed_data"
  | "expression_csv"
  | "homolog_csv";

/** Task status extended with ``queued`` (backend returns it). */
type ImportTaskStatus = TaskStatus | "queued";

interface ImportTask {
  id: number;
  filename: string;
  type: ImportType;
  status: ImportTaskStatus;
  progress: number;
  total_records: number;
  processed_records: number;
  celery_task_id: string | null;
  submitted_by: string | null;
  file_path: string;
  error_message: string | null;
  submitted_at: string;
  completed_at: string | null;
}

interface ImportStatus {
  id: number;
  status: ImportTaskStatus;
  celery_status: string;
  progress: number;
  processed_records: number;
  total_records: number;
  error_message: string | null;
}

interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TYPE_LABELS: Record<ImportType, string> = {
  vcf: "VCF",
  gff3: "GFF3",
  fasta: "FASTA",
  blast_db: "BLAST DB",
  seed_data: "Seed Data",
  expression_csv: "Expression CSV",
  homolog_csv: "Homolog CSV",
};

const ALL_IMPORT_TYPES: ImportType[] = [
  "vcf",
  "gff3",
  "fasta",
  "blast_db",
  "seed_data",
  "expression_csv",
  "homolog_csv",
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ImportsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");

  // Upload dialog state
  const [showUpload, setShowUpload] = useState(false);
  const [uploadType, setUploadType] = useState<ImportType>("vcf");
  const [uploadFilename, setUploadFilename] = useState("");
  const [uploadFilePath, setUploadFilePath] = useState("");

  // Live status updates for running tasks
  const [liveStatuses, setLiveStatuses] = useState<
    Map<number, ImportStatus>
  >(new Map());

  // -----------------------------------------------------------------------
  // Queries
  // -----------------------------------------------------------------------

  const { data, isLoading } = useQuery<PaginatedResponse<ImportTask>>({
    queryKey: ["admin-imports", page, search],
    queryFn: () =>
      http.get("/admin/imports", {
        params: { page, page_size: 20, search },
      }),
    placeholderData: { items: [], total: 0, page, page_size: 20 },
  });

  const tasks = data?.items ?? [];
  const hasRunning = tasks.some(
    (t) => t.status === "running" || t.status === "queued",
  );

  // -----------------------------------------------------------------------
  // Mutations
  // -----------------------------------------------------------------------

  const submitMutation = useMutation({
    mutationFn: (body: {
      filename: string;
      type: ImportType;
      file_path: string;
      submitted_by: string;
    }) =>
      http.post("/admin/imports", {
        json: body,
        timeoutMs: 30_000,
      }),
    onSuccess: () => {
      setShowUpload(false);
      setUploadFilename("");
      setUploadFilePath("");
      setUploadType("vcf");
      queryClient.invalidateQueries({ queryKey: ["admin-imports"] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (id: number) => http.delete(`/admin/imports/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-imports"] });
    },
  });

  const retryMutation = useMutation({
    mutationFn: (id: number) => http.post(`/admin/imports/${id}/retry`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-imports"] });
    },
  });

  // -----------------------------------------------------------------------
  // Live status polling – every 3 s when there are running tasks
  // -----------------------------------------------------------------------

  useEffect(() => {
    if (!hasRunning) {
      setLiveStatuses(new Map());
      return;
    }

    const runningIds = tasks
      .filter((t) => t.status === "running" || t.status === "queued")
      .map((t) => t.id);

    const poll = async () => {
      const updates: [number, ImportStatus][] = [];
      for (const id of runningIds) {
        try {
          const status = await http.get<ImportStatus>(
            `/admin/imports/${id}/status`,
            { timeoutMs: 5_000 },
          );
          updates.push([id, status]);
        } catch {
          // Ignore transient errors during polling
        }
      }
      if (updates.length > 0) {
        setLiveStatuses((prev) => {
          const next = new Map(prev);
          for (const [id, status] of updates) {
            next.set(id, status);
          }
          return next;
        });
      }
    };

    const interval = setInterval(poll, 3000);
    // Also poll immediately on mount
    poll();

    return () => clearInterval(interval);
  }, [hasRunning, tasks]);

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  /** Merge live status data into a task row. */
  const enrichTask = useCallback(
    (task: ImportTask): ImportTask => {
      const live = liveStatuses.get(task.id);
      if (!live) return task;
      return {
        ...task,
        status: live.status as ImportTaskStatus,
        progress: live.progress,
        processed_records: live.processed_records,
        total_records: live.total_records,
        error_message: live.error_message,
      };
    },
    [liveStatuses],
  );

  function handleUploadSubmit() {
    if (!uploadFilename.trim() || !uploadFilePath.trim()) return;
    submitMutation.mutate({
      filename: uploadFilename.trim(),
      type: uploadType,
      file_path: uploadFilePath.trim(),
      submitted_by: user?.username ?? "unknown",
    });
  }

  function handleCancel(taskId: number) {
    if (confirm("Cancel this import task?")) {
      cancelMutation.mutate(taskId);
    }
  }

  function handleRetry(taskId: number) {
    retryMutation.mutate(taskId);
  }

  // -----------------------------------------------------------------------
  // Columns
  // -----------------------------------------------------------------------

  const columns: DataTableColumn<ImportTask>[] = [
    {
      key: "filename",
      header: "File",
      sortable: true,
      sortAccessor: (t) => t.filename,
      cell: (task) => {
        const t = enrichTask(task);
        return (
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="size-4 text-muted-foreground" />
            <div>
              <p className="font-medium">{t.filename}</p>
              <p className="text-xs text-muted-foreground">
                {TYPE_LABELS[t.type]}
              </p>
            </div>
          </div>
        );
      },
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortAccessor: (t) => t.status,
      cell: (task) => {
        const t = enrichTask(task);
        return <StatusBadge status={t.status} type="task" />;
      },
    },
    {
      key: "progress",
      header: "Progress",
      cell: (task) => {
        const t = enrichTask(task);
        return (
          <div className="w-40">
            <div className="flex items-center justify-between text-xs">
              <span className="font-mono">
                {t.processed_records.toLocaleString()} /{" "}
                {t.total_records.toLocaleString()}
              </span>
              <span className="text-muted-foreground">{t.progress}%</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${t.progress}%` }}
                role="progressbar"
                aria-valuenow={t.progress}
                aria-valuemin={0}
                aria-valuemax={100}
              />
            </div>
          </div>
        );
      },
    },
    {
      key: "submitted_by",
      header: "Submitted By",
      cell: (task) => {
        const t = enrichTask(task);
        return <span className="text-sm">{t.submitted_by}</span>;
      },
    },
    {
      key: "submitted_at",
      header: "Submitted",
      sortable: true,
      sortAccessor: (t) => t.submitted_at,
      cell: (task) => {
        const t = enrichTask(task);
        return (
          <span className="text-sm text-muted-foreground">
            {t.submitted_at}
          </span>
        );
      },
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: (task) => {
        const t = enrichTask(task);
        if (t.status === "failed") {
          return (
            <div className="flex items-center gap-1">
              {t.error_message ? (
                <Badge
                  variant="destructive"
                  title={t.error_message}
                  className="cursor-help"
                >
                  View Error
                </Badge>
              ) : null}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleRetry(t.id)}
                disabled={retryMutation.isPending}
              >
                <RotateCcw className="size-3.5" />
                Retry
              </Button>
            </div>
          );
        }
        if (t.status === "running" || t.status === "queued") {
          return (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleCancel(t.id)}
              disabled={cancelMutation.isPending}
              className="text-destructive hover:text-destructive"
            >
              <XCircle className="size-3.5" />
              Cancel
            </Button>
          );
        }
        return (
          <Button variant="ghost" size="sm">
            Details
          </Button>
        );
      },
    },
  ];

  // -----------------------------------------------------------------------
  // Stats (from paginated data – approximates total counts)
  // -----------------------------------------------------------------------

  // Note: these stats are computed from the current page, not the full set.
  // For production accuracy, the backend should expose aggregates.
  const stats = {
    total: data?.total ?? 0,
    running: tasks.filter(
      (t) => t.status === "running" || t.status === "queued",
    ).length,
    failed: tasks.filter((t) => t.status === "failed").length,
    completed: tasks.filter((t) => t.status === "completed").length,
  };

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-serif text-2xl font-semibold">Data Imports</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Monitor and manage data import tasks (VCF, GFF3, FASTA, BLAST
            databases, expression data, homologs).
          </p>
        </div>
        <Button onClick={() => setShowUpload(true)}>
          <Upload className="size-4" />
          New Import
        </Button>
      </div>

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-4">
        {[
          { label: "Total Tasks", value: stats.total, icon: Database },
          {
            label: "Running",
            value: stats.running,
            icon: Loader2,
            iconClass: "animate-spin",
          },
          { label: "Completed", value: stats.completed, icon: Upload },
          { label: "Failed", value: stats.failed, icon: XCircle },
        ].map((s) => (
          <div
            key={s.label}
            className="rounded-xl border border-border bg-card p-4"
          >
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {s.label}
              </p>
              <s.icon
                className={cn(
                  "size-4 text-muted-foreground",
                  s.iconClass,
                )}
              />
            </div>
            <p className="mt-2 font-serif text-2xl font-semibold">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Search */}
      <Input
        placeholder="Search import tasks..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="max-w-xs"
      />

      {/* Table */}
      <DataTable
        columns={columns}
        data={tasks}
        rowKey={(t) => String(t.id)}
        loading={isLoading}
        page={page}
        pageSize={20}
        total={data?.total ?? 0}
        onPageChange={setPage}
        emptyTitle="No import tasks"
        emptyDescription="Submit a new import to get started."
      />

      {/* Upload dialog */}
      <Dialog open={showUpload} onOpenChange={setShowUpload}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Import</DialogTitle>
            <DialogDescription>
              Submit a new data import task. The file should already be uploaded
              to S3 — provide the S3 URI below.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Import type */}
            <div className="space-y-1.5">
              <Label htmlFor="import-type">Import Type</Label>
              <Select
                value={uploadType}
                onValueChange={(v) => setUploadType(v as ImportType)}
              >
                <SelectTrigger id="import-type">
                  <SelectValue placeholder="Select type" />
                </SelectTrigger>
                <SelectContent>
                  {ALL_IMPORT_TYPES.map((type) => (
                    <SelectItem key={type} value={type}>
                      {TYPE_LABELS[type]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Filename */}
            <div className="space-y-1.5">
              <Label htmlFor="import-filename">Filename</Label>
              <Input
                id="import-filename"
                placeholder="e.g. expression_data.csv"
                value={uploadFilename}
                onChange={(e) => setUploadFilename(e.target.value)}
              />
            </div>

            {/* S3 file path */}
            <div className="space-y-1.5">
              <Label htmlFor="import-filepath">S3 File Path</Label>
              <Input
                id="import-filepath"
                placeholder="s3://bucket-name/path/to/file.csv"
                value={uploadFilePath}
                onChange={(e) => setUploadFilePath(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                The S3 URI where the file has already been uploaded.
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowUpload(false)}
              disabled={submitMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              onClick={handleUploadSubmit}
              disabled={
                submitMutation.isPending ||
                !uploadFilename.trim() ||
                !uploadFilePath.trim()
              }
            >
              {submitMutation.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Submitting…
                </>
              ) : (
                <>
                  <Upload className="size-4" />
                  Submit Import
                </>
              )}
            </Button>
          </DialogFooter>

          {submitMutation.isError ? (
            <p className="text-sm text-destructive">
              {submitMutation.error instanceof Error
                ? submitMutation.error.message
                : "Failed to submit import task."}
            </p>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

