import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Upload,
  FileSpreadsheet,
  Database,
  RotateCcw,
  XCircle,
  CheckCircle2,
  Loader2,
  Download,
} from "lucide-react";
import { http, apiBaseUrl, getAccessToken } from "@soymutdb/api-client";
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
  PageHeader,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatCard,
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
  | "homolog_csv"
  | "module_tsv";

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
  module_tsv: "Module Data",
};

const ALL_IMPORT_TYPES: ImportType[] = [
  "vcf",
  "gff3",
  "fasta",
  "blast_db",
  "seed_data",
  "expression_csv",
  "homolog_csv",
  "module_tsv",
];

/** File extensions accepted for ``module_tsv`` (multi-format module import). */
const MODULE_FORMAT_EXTENSIONS = [".tsv", ".txt", ".csv", ".xlsx"] as const;

/** Available template download formats (backend ``format`` query param). */
const MODULE_TEMPLATE_FORMATS = [
  { value: "tsv", label: "TSV" },
  { value: "csv", label: "CSV" },
  { value: "xlsx", label: "XLSX" },
] as const;

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
  const [uploadModuleKey, setUploadModuleKey] = useState("genes");
  const [uploadChecksum, setUploadChecksum] = useState("");
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Module template download state
  const [templateModuleKey, setTemplateModuleKey] = useState("genes");
  const [templateFormat, setTemplateFormat] = useState<string>("tsv");
  const [templateDownloading, setTemplateDownloading] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);

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
      module_key?: string;
      checksum?: string;
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
      setUploadModuleKey("genes");
      setUploadChecksum("");
      setUploadError(null);
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
    const filename = uploadFilename.trim();
    if (!filename || !uploadFilePath.trim()) return;
    setUploadError(null);

    // Module data imports must use a supported multi-format extension.
    if (uploadType === "module_tsv") {
      const ext = filename.toLowerCase().match(/\.[a-z0-9]+$/)?.[0];
      if (!ext || !(MODULE_FORMAT_EXTENSIONS as readonly string[]).includes(ext)) {
        setUploadError(
          `Module data files must use one of ${MODULE_FORMAT_EXTENSIONS.join(" / ")}.`,
        );
        return;
      }
      if (!uploadModuleKey.trim()) {
        setUploadError("Module key is required for module data imports.");
        return;
      }
      if (!uploadChecksum.trim()) {
        setUploadError("Checksum is required for module data imports.");
        return;
      }
    }

    submitMutation.mutate({
      filename,
      type: uploadType,
      file_path: uploadFilePath.trim(),
      submitted_by: user?.username ?? "unknown",
      module_key: uploadType === "module_tsv" ? uploadModuleKey.trim() : undefined,
      checksum: uploadType === "module_tsv" ? uploadChecksum.trim() : undefined,
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

  /** Download a module starter template in the selected format. */
  async function handleTemplateDownload() {
    const key = templateModuleKey.trim();
    if (!key) {
      setTemplateError("Module key is required.");
      return;
    }
    setTemplateDownloading(true);
    setTemplateError(null);
    try {
      const url = `${apiBaseUrl}/admin/modules/${encodeURIComponent(key)}/template?format=${encodeURIComponent(templateFormat)}`;
      const headers: Record<string, string> = {
        Accept: "application/octet-stream, application/json",
      };
      const token = getAccessToken();
      if (token) headers.Authorization = `Bearer ${token}`;

      const res = await fetch(url, { headers, credentials: "include" });
      if (!res.ok) {
        throw new Error(`Template download failed (${res.status})`);
      }
      const blob = await res.blob();
      const disposition = res.headers.get("content-disposition") ?? "";
      const match = disposition.match(/filename="?([^";]+)"?/);
      const filename = match?.[1] ?? `${key}.${templateFormat}`;
      const downloadUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = downloadUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(downloadUrl);
    } catch (err) {
      setTemplateError(err instanceof Error ? err.message : "Template download failed.");
    } finally {
      setTemplateDownloading(false);
    }
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
        const isRunning = t.status === "running" || t.status === "queued";
        return (
          <div className="w-40">
            <div className="flex items-center justify-between text-xs">
              <span className="font-mono tabular-nums">
                {t.processed_records.toLocaleString()} /{" "}
                {t.total_records.toLocaleString()}
              </span>
              <span className="font-mono tabular-nums text-muted-foreground">{t.progress}%</span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full rounded-full bg-primary transition-all",
                  isRunning && "progress-running",
                  t.status === "failed" && "bg-destructive",
                )}
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
      <PageHeader
        title="Data Imports"
        description="Monitor and manage data import tasks (VCF, GFF3, FASTA, BLAST databases, expression data, homologs)."
        actions={
          <Button onClick={() => setShowUpload(true)}>
            <Upload className="size-4" />
            New Import
          </Button>
        }
      />

      {/* Module template download */}
      <div className="rounded-lg border bg-card p-4">
        <div className="mb-3 flex items-center gap-2">
          <Database className="size-4 text-muted-foreground" />
          <span className="text-sm font-medium">Module template download</span>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="template-module-key">Module Key</Label>
            <Input
              id="template-module-key"
              value={templateModuleKey}
              onChange={(e) => setTemplateModuleKey(e.target.value)}
              className="w-40"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="template-format">Format</Label>
            <Select value={templateFormat} onValueChange={setTemplateFormat}>
              <SelectTrigger id="template-format" className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MODULE_TEMPLATE_FORMATS.map((f) => (
                  <SelectItem key={f.value} value={f.value}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleTemplateDownload}
            disabled={templateDownloading || !templateModuleKey.trim()}
          >
            {templateDownloading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Download className="size-4" />
            )}
            Download
          </Button>
        </div>
        {templateError ? (
          <p className="mt-2 text-sm text-destructive">{templateError}</p>
        ) : null}
        <p className="mt-2 text-xs text-muted-foreground">
          Starter template for a module schema (genes). Format: TSV / CSV / XLSX.
        </p>
      </div>

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total Tasks" value={stats.total} icon={<Database className="size-5" />} />
        <StatCard
          label="Running"
          value={stats.running}
          icon={<Loader2 className={cn("size-5", stats.running > 0 && "animate-spin")} />}
        />
        <StatCard label="Completed" value={stats.completed} icon={<CheckCircle2 className="size-5" />} />
        <StatCard label="Failed" value={stats.failed} icon={<XCircle className="size-5" />} />
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
                placeholder={
                  uploadType === "module_tsv"
                    ? "e.g. genes.tsv / genes.txt / genes.csv / genes.xlsx"
                    : "e.g. expression_data.csv"
                }
                value={uploadFilename}
                onChange={(e) => {
                  setUploadFilename(e.target.value);
                  setUploadError(null);
                }}
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

            {/* Module-specific fields */}
            {uploadType === "module_tsv" ? (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="import-module-key">Module Key</Label>
                  <Input
                    id="import-module-key"
                    placeholder="genes"
                    value={uploadModuleKey}
                    onChange={(e) => setUploadModuleKey(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Server-owned schema key. Supports .tsv / .txt / .csv / .xlsx.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="import-checksum">Checksum</Label>
                  <Input
                    id="import-checksum"
                    placeholder="sha256 of the source file (required)"
                    value={uploadChecksum}
                    onChange={(e) => setUploadChecksum(e.target.value)}
                  />
                </div>
              </>
            ) : null}

            {uploadError ? (
              <p className="text-sm text-destructive">{uploadError}</p>
            ) : null}
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

