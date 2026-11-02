import { useTranslation } from "react-i18next";
import { Link } from "@tanstack/react-router";
import { CloudUploadOutlined, FileExcelOutlined, DatabaseOutlined, RedoOutlined, CloseCircleOutlined, CheckCircleOutlined, LoadingOutlined, DownloadOutlined } from "@ant-design/icons";
import { Skeleton, Badge, Button, Input, Modal, PageContainer, Select, Typography, App } from "@/lib/antd";
import { StatCard } from "../components/stat-card";
import { ConfirmDialog } from "../components/confirm-dialog";
import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { http, authRequestBlob, capabilitiesApi, adminImportStudioApi, type ImportDraftListItemResponse, type ImportDraftResponse } from "@soymutdb/api-client";
import { cn } from "../lib/cn";
import { summarizeImportPage } from "../lib/import-task-stats";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { ImportPreviewTable } from "../components/import-preview-table";
import { ImportDraftEditor } from "../components/import-draft-editor";
import { StatusBadge, type TaskStatus } from "../components/status-badge";
import {
  uploadModuleFile,
  fetchModulePreview,
  describeUploadSource,
  type UploadedObject,
  type ModulePreviewResult,
} from "../lib/module-import-upload";
import { resolveFeatureState } from "../lib/capability-state";
import {
  buildImportSubmission,
  createImportIdempotencyKey,
  describeImportIntent,
  parseDataSetId,
  parseModuleReleaseId,
  resolveIdempotencyKey,
  validateModuleImport,
  type ImportSubmission,
} from "../lib/import-submission";

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

/**
 * Historical task labels remain in TYPE_LABELS so previously submitted jobs
 * continue to render correctly. New submissions expose only durable writers.
 */
export const AVAILABLE_SUBMISSION_IMPORT_TYPES = ["module_tsv"] as const;
export const DEFAULT_SUBMISSION_IMPORT_TYPE: (typeof AVAILABLE_SUBMISSION_IMPORT_TYPES)[number] =
  "module_tsv";

/** Available template download formats (backend ``format`` query param). */
const MODULE_TEMPLATE_FORMATS = [
  { value: "tsv", label: "TSV" },
  { value: "csv", label: "CSV" },
  { value: "xlsx", label: "XLSX" },
] as const;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface ImportsPageProps {
  /** Opens the existing upload dialog for the route-compatible submit entry. */
  initialUploadOpen?: boolean;
}

export default function ImportsPage({ initialUploadOpen = false }: ImportsPageProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  // A resume link names a server-created draft; the legacy upload wizard never
  // supplies or recreates this identifier.
  const resumeDraftId = typeof window === "undefined"
    ? null
    : new URLSearchParams(window.location.search).get("draft");

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");

  // CloudUploadOutlined dialog state
  const [showUpload, setShowUpload] = useState(initialUploadOpen);
  const [uploadType, setUploadType] = useState<ImportType>(DEFAULT_SUBMISSION_IMPORT_TYPE);
  const [uploadFilename, setUploadFilename] = useState("");
  const [uploadFilePath, setUploadFilePath] = useState("");
  const [uploadModuleKey, setUploadModuleKey] = useState("genes");
  const [uploadDataSetId, setUploadDataSetId] = useState("1");
  const [uploadReleaseId, setUploadReleaseId] = useState("");
  const [uploadChecksum, setUploadChecksum] = useState("");
  const [uploadIdempotencyKey, setUploadIdempotencyKey] = useState("");
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Local file upload state (Phase D). ``uploadMode`` selects local multipart
  // direct-upload vs. the advanced S3 URI flow.
  const [uploadMode, setUploadMode] = useState<"local" | "s3">("local");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [previewState, setPreviewState] = useState<
    ModulePreviewResult | { status: "checking" } | null
  >(null);
  const previewRequestToken = useRef(0);

  // Synchronous in-flight guard. `uploading` / `submitMutation.isPending` only
  // disable the button after React re-renders, so two clicks inside one tick
  // both used to clear every guard and start a second multipart session (and a
  // second POST /admin/imports).
  const submittingRef = useRef(false);
  // Payload signature the current idempotency key was issued for. The API
  // answers a repeated key with the previously created task, so a key is only
  // reusable while the intent behind it is unchanged.
  const idempotencyIntentRef = useRef<string | null>(null);
  // Last completed browser-direct upload, so retrying a failed submission
  // reuses the finished object instead of transferring the whole file again.
  const uploadedSourceRef = useRef<{ identity: string; uploaded: UploadedObject } | null>(null);

  // Module template download state
  const [templateModuleKey, setTemplateModuleKey] = useState("genes");
  const [templateFormat, setTemplateFormat] = useState<string>("tsv");
  const [templateDownloading, setTemplateDownloading] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);

  // Live status updates for running tasks
  const [liveStatuses, setLiveStatuses] = useState<
    Map<number, ImportStatus>
  >(new Map());

  // Cancel / retry are confirmed and every rejection is reported.
  const [cancelTarget, setCancelTarget] = useState<{ id: number; filename: string } | null>(null);
  const [retryTarget, setRetryTarget] = useState<{ id: number; filename: string } | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);

  // -----------------------------------------------------------------------
  // Queries
  // -----------------------------------------------------------------------

  const { data, isLoading, isError, isFetching } = useQuery<PaginatedResponse<ImportTask>>({
    queryKey: ["admin-imports", page, search],
    queryFn: () =>
      http.get("/admin/imports", {
        params: { page, page_size: 20, search },
      }),
  });

  const draftsQuery = useQuery<ImportDraftListItemResponse[]>({
    queryKey: ["admin-import-studio-drafts"],
    queryFn: () => adminImportStudioApi.listDrafts(),
  });
  const resumeDraftQuery = useQuery<ImportDraftResponse>({
    queryKey: ["admin-import-studio-draft", resumeDraftId],
    queryFn: () => adminImportStudioApi.getDraft(resumeDraftId!),
    enabled: Boolean(resumeDraftId),
  });

  const capabilitiesQuery = useQuery({
    queryKey: ["public-capabilities"],
    queryFn: capabilitiesApi.get,
    staleTime: 30_000,
  });
  const capabilitySnapshot = {
    pending: capabilitiesQuery.isPending,
    error: capabilitiesQuery.isError,
    features: capabilitiesQuery.data?.features,
  };
  const moduleImportState = resolveFeatureState(capabilitySnapshot, "imports.module_tsv");
  const xlsxImportState = resolveFeatureState(capabilitySnapshot, "imports.module_xlsx");
  const localUploadState = resolveFeatureState(capabilitySnapshot, "imports.local_upload");
  const moduleImportEnabled = moduleImportState === "enabled";
  const xlsxImportEnabled = xlsxImportState === "enabled";
  const localUploadEnabled = localUploadState === "enabled";
  // Capability loss does not need a synchronizing effect: the rendered and
  // submitted source are derived from the current server snapshot.
  const effectiveUploadMode = localUploadEnabled ? uploadMode : "s3";

  const tasks = useMemo(() => data?.items ?? [], [data?.items]);
  // The browser gate keys off the request itself: "loading" while
  // GET /admin/imports is in flight, then exactly one of "ready" (rows or the
  // empty state) or "error".
  const taskListState = isError ? "error" : isFetching ? "loading" : "ready";
  const hasRunning = tasks.some(
    (t) => t.status === "running" || t.status === "queued",
  );

  // -----------------------------------------------------------------------
  // Mutations
  // -----------------------------------------------------------------------

  const submitMutation = useMutation({
    mutationFn: (body: ImportSubmission) =>
      http.post("/admin/imports", {
        json: body,
        timeoutMs: 30_000,
      }),
    onSuccess: () => {
      previewRequestToken.current += 1;
      setShowUpload(false);
      setUploadFilename("");
      setUploadFilePath("");
      setUploadType(DEFAULT_SUBMISSION_IMPORT_TYPE);
      setUploadModuleKey("genes");
      setUploadDataSetId("1");
      setUploadReleaseId("");
      setUploadChecksum("");
      setUploadIdempotencyKey("");
      setUploadError(null);
      setUploadFile(null);
      setUploadProgress(0);
      setUploading(false);
      setUploadMode("local");
      setPreviewState(null);
      idempotencyIntentRef.current = null;
      uploadedSourceRef.current = null;
      queryClient.invalidateQueries({ queryKey: ["admin-imports"] });
    },
    onSettled: () => {
      submittingRef.current = false;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (id: number) => http.delete(`/admin/imports/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-imports"] });
      setCancelTarget(null);
      setCancelError(null);
      message.success(t("admin.importPage.cancelSucceeded", { defaultValue: "The import task was cancelled." }));
    },
    onError: (error) => {
      // The confirmation dialog stays open and explains the refusal; a
      // rejected cancel used to leave the operator with no signal at all.
      setCancelError(error instanceof Error ? error.message : String(error));
      message.error(t("admin.importPage.cancelFailed", { defaultValue: "The import task could not be cancelled." }));
    },
  });

  const retryMutation = useMutation({
    mutationFn: (id: number) => http.post(`/admin/imports/${id}/retry`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-imports"] });
      setRetryTarget(null);
      setRetryError(null);
      message.success(t("admin.importPage.retrySucceeded", { defaultValue: "The import task was queued for a retry." }));
    },
    onError: (error) => {
      setRetryError(error instanceof Error ? error.message : String(error));
      message.error(t("admin.importPage.retryFailed", { defaultValue: "The import task could not be retried." }));
    },
  });

  // -----------------------------------------------------------------------
  // Live status polling – every 3 s when there are running tasks
  // -----------------------------------------------------------------------

  useEffect(() => {
    if (!hasRunning) return;

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

  function openUploadDialog() {
    // Every dialog session starts from a clean draft. Previously the modal kept
    // the previously chosen file, release ID, checksum and preview while minting
    // a new idempotency key, so reopening let the old file be submitted again as
    // a second task with no visible trace of what was carried over.
    setUploadDataSetId("1");
    setUploadIdempotencyKey(createImportIdempotencyKey());
    idempotencyIntentRef.current = null;
    uploadedSourceRef.current = null;
    setUploadType(DEFAULT_SUBMISSION_IMPORT_TYPE);
    setUploadMode("local");
    setUploadFile(null);
    setUploadFilename("");
    setUploadFilePath("");
    setUploadModuleKey("genes");
    setUploadReleaseId("");
    setUploadChecksum("");
    setUploadError(null);
    setUploading(false);
    setUploadProgress(0);
    invalidatePreview();
    setShowUpload(true);
  }

  function submitImport(
    input: Omit<ImportSubmission, "data_set_id" | "idempotency_key" | "release_id">,
    dataSetId: number,
  ): boolean {
    const intent = describeImportIntent({
      filename: input.filename,
      type: input.type,
      dataSetId,
      releaseId: uploadType === "module_tsv" ? uploadReleaseId : undefined,
      objectKey: input.object_key,
      filePath: input.file_path,
      moduleKey: input.module_key,
      checksum: input.checksum,
    });
    const idempotencyKey = resolveIdempotencyKey({
      currentKey: uploadIdempotencyKey,
      currentIntent: idempotencyIntentRef.current,
      nextIntent: intent,
      createKey: createImportIdempotencyKey,
    });
    idempotencyIntentRef.current = intent;
    if (!uploadIdempotencyKey) setUploadIdempotencyKey(idempotencyKey);
    else if (idempotencyKey !== uploadIdempotencyKey) setUploadIdempotencyKey(idempotencyKey);
    try {
      submitMutation.mutate(
        buildImportSubmission({
          filename: input.filename,
          type: input.type,
          filePath: input.file_path,
          objectKey: input.object_key,
          moduleKey: input.module_key,
          checksum: input.checksum,
          dataSetIdInput: String(dataSetId),
          releaseIdInput: uploadReleaseId,
          idempotencyKey,
        }),
      );
      return true;
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Invalid import submission.");
      return false;
    }
  }

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

  async function handleUploadSubmit() {
    if (submittingRef.current) return;
    submittingRef.current = true;
    try {
      // The mutation's `onSettled` releases the guard once the server has
      // answered a request that was actually sent; every early exit below has
      // to release it here instead.
      if (!(await runImportSubmission())) submittingRef.current = false;
    } catch (error) {
      submittingRef.current = false;
      setUploadError(error instanceof Error ? error.message : "Invalid import submission.");
    }
  }

  /**
   * Validate the dialog, upload if the local source changed, and submit.
   * Returns true only when a request was handed to the mutation (which then
   * owns releasing the in-flight guard).
   */
  async function runImportSubmission(): Promise<boolean> {
    setUploadError(null);

    if (!capabilitiesQuery.isSuccess) {
      setUploadError("Import capabilities are unavailable. Refresh and try again.");
      return false;
    }
    if (uploadType === "module_tsv" && !moduleImportEnabled) {
      setUploadError("Module imports are disabled.");
      return false;
    }
    if (uploadType === "module_tsv") {
      try {
        parseModuleReleaseId(uploadReleaseId);
      } catch (error) {
        setUploadError(error instanceof Error ? error.message : "A release ID is required.");
        return false;
      }
    }
    let dataSetId: number;
    try {
      dataSetId = parseDataSetId(uploadDataSetId);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "A data set ID is required.");
      return false;
    }

    if (effectiveUploadMode === "local") {
      if (!uploadFile) {
        setUploadError("Choose a file to upload.");
        return false;
      }
      const filename = uploadFile.name;
      const moduleKey = uploadModuleKey.trim();
      if (uploadType === "module_tsv") {
        const invalid = validateModuleImport({ filename, moduleKey, sourceMode: "local" });
        if (invalid) {
          setUploadError(invalid);
          return false;
        }
      }

      const uploadIdentity = describeUploadSource({
        filename,
        size: uploadFile.size,
        lastModified: uploadFile.lastModified,
        type: uploadType,
        moduleKey: uploadType === "module_tsv" ? moduleKey : undefined,
        dataSetId,
      });
      const alreadyUploaded = uploadedSourceRef.current;
      let uploaded: UploadedObject;
      if (alreadyUploaded && alreadyUploaded.identity === uploadIdentity) {
        // The bytes already reached object storage under this data set's key.
        // Re-uploading after a failed POST /admin/imports would create a second
        // object and hand the server an orphan.
        uploaded = alreadyUploaded.uploaded;
      } else {
        setUploading(true);
        setUploadProgress(0);
        try {
          // Browser-direct multipart upload — file bytes never hit the API.
          uploaded = await uploadModuleFile({
            filename,
            type: uploadType,
            file: uploadFile,
            dataSetId,
            onProgress: (p) => setUploadProgress(p.percent),
          });
        } catch (err) {
          setUploadError(
            err instanceof Error ? err.message : "CloudUploadOutlined failed.",
          );
          return false;
        } finally {
          setUploading(false);
        }
        uploadedSourceRef.current = { identity: uploadIdentity, uploaded };
      }
      return submitImport(
        {
          filename,
          type: uploadType,
          object_key: uploaded.object_key,
          module_key: uploadType === "module_tsv" ? moduleKey : undefined,
          checksum: uploadType === "module_tsv" ? uploaded.sha256 : undefined,
        },
        dataSetId,
      );
    }

    // Advanced S3 URI mode.
    const filename = uploadFilename.trim();
    if (!filename || !uploadFilePath.trim()) {
      setUploadError("Filename and S3 path are required in S3 mode.");
      return false;
    }
    const moduleKey = uploadModuleKey.trim();
    if (uploadType === "module_tsv") {
      const invalid = validateModuleImport({
        filename,
        moduleKey,
        sourceMode: "s3",
        checksum: uploadChecksum,
      });
      if (invalid) {
        setUploadError(invalid);
        return false;
      }
    }

    return submitImport(
      {
        filename,
        type: uploadType,
        file_path: uploadFilePath.trim(),
        module_key: uploadType === "module_tsv" ? moduleKey : undefined,
        checksum: uploadType === "module_tsv" ? uploadChecksum.trim() : undefined,
      },
      dataSetId,
    );
  }

  function invalidatePreview() {
    previewRequestToken.current += 1;
    setPreviewState(null);
  }

  /**
   * Close the dialog and drop any preview still in flight, so a slow response
   * cannot paint the previous session's rows into the next one.
   */
  function closeUploadDialog() {
    invalidatePreview();
    setUploadError(null);
    setShowUpload(false);
  }

  /** Request a bounded, read-only validation preview for a local module file. */
  function checkPreview() {
    if (!uploadFile || uploadType !== "module_tsv") return;
    const requestToken = ++previewRequestToken.current;
    setPreviewState({ status: "checking" });
    void fetchModulePreview({
      filename: uploadFile.name,
      moduleKey: uploadModuleKey.trim() || "genes",
      file: uploadFile,
    })
      .then((result) => {
        if (previewRequestToken.current === requestToken) {
          setPreviewState(result);
        }
      })
      .catch((error: unknown) => {
        if (previewRequestToken.current === requestToken) {
          setPreviewState({
            status: "unavailable",
            reason: error instanceof Error ? error.message : "Preview request failed.",
          });
        }
      });
  }

  function handleCancel(task: ImportTask) {
    // The native `window.confirm` was an unstyled English prompt inside a
    // Chinese console; the shared dialog is used instead.
    setCancelError(null);
    setCancelTarget({ id: task.id, filename: task.filename });
  }

  function handleRetry(task: ImportTask) {
    setRetryError(null);
    setRetryTarget({ id: task.id, filename: task.filename });
  }

  /** DownloadOutlined a module starter template in the selected format. */
  async function handleTemplateDownload() {
    const key = templateModuleKey.trim();
    if (!key) {
      setTemplateError("Module key is required.");
      return;
    }
    setTemplateDownloading(true);
    setTemplateError(null);
    try {
      const path = `/admin/modules/${encodeURIComponent(key)}/template?format=${encodeURIComponent(templateFormat)}`;
      // Binary downloads still go through the shared auth-aware client so
      // refresh-on-401, CSRF, API origin, and credentials stay consistent.
      const blob = await authRequestBlob(path, {
        headers: { Accept: "application/octet-stream, application/json" },
      });
      const filename = `${key}.${templateFormat}`;
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
            <FileExcelOutlined className="size-4 text-muted-foreground" />
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
                  color="red"
                  title={t.error_message}
                  className="cursor-help"
                >
                  View Error
                </Badge>
              ) : null}
              <Button
                type="text"
                size="small"
                data-testid="imports-retry-task"
                onClick={() => handleRetry(t)}
                disabled={retryMutation.isPending}
              >
                <RedoOutlined className="size-3.5" />
                Retry
              </Button>
            </div>
          );
        }
        if (t.status === "running" || t.status === "queued") {
          return (
            <Button
              type="text"
              size="small"
              data-testid="imports-cancel-task"
              onClick={() => handleCancel(t)}
              disabled={cancelMutation.isPending}
              className="text-destructive hover:text-destructive"
            >
              <CloseCircleOutlined className="size-3.5" />
              Cancel
            </Button>
          );
        }
        return (
              <Button type="text" size="small">
                {/* The task detail route reads /admin/imports/{id}; the control
                    used to have no handler at all, so a finished task had no
                    reachable detail view. */}
                <Link to="/imports/$taskId" params={{ taskId: String(t.id) }}>
                  Details
                </Link>
          </Button>
        );
      },
    },
  ];

  // -----------------------------------------------------------------------
  // The filtered total spans all pages; status counts describe the visible page.
  // -----------------------------------------------------------------------

  const stats = summarizeImportPage(tasks, data?.total ?? 0);

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <PageContainer
      title={t("admin.importPage.title")}
      subTitle={t("admin.importPage.subtitle")}
      extra={[
        <Button key="new-import" type="primary" data-testid="imports-new" onClick={openUploadDialog} disabled={!capabilitiesQuery.isSuccess} icon={<CloudUploadOutlined aria-hidden />} aria-label={t("admin.importPage.newImport")}>{t("admin.importPage.newImport")}</Button>,
      ]}
    >
      <div className="space-y-6">
        {capabilitiesQuery.isPending ? (
          <p role="status" className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
            Loading import capabilities…
          </p>
        ) : null}
        {capabilitiesQuery.isError ? (
          <p
            role="alert"
            aria-label={t("admin.importPage.capabilitiesUnavailable")}
            className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
          >
            Unable to load import capabilities. Import actions remain unavailable.
          </p>
        ) : null}
        {capabilitiesQuery.isSuccess && moduleImportState === "disabled" ? (
          <p className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
            Module imports are disabled.
          </p>
        ) : null}

        {/* Module template download */}
        <div className="rounded-lg border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <DatabaseOutlined className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium">{t("admin.importPage.templateDownload")}</span>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1.5">
              <label htmlFor="template-module-key">{t("admin.importPage.moduleKey")}</label>
              <Input
                id="template-module-key"
                value={templateModuleKey}
                onChange={(e) => setTemplateModuleKey(e.target.value)}
                className="w-40"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="template-format">{t("admin.importPage.format")}</label>
              <Select
                value={templateFormat}
                onChange={setTemplateFormat}
                options={MODULE_TEMPLATE_FORMATS.map((f) => ({
                  value: f.value,
                  label: f.label,
                  disabled: f.value === "xlsx" && !xlsxImportEnabled,
                }))}
              />
            </div>
            <Button
              type="default"
              size="small"
              onClick={handleTemplateDownload}
              disabled={
                templateDownloading ||
                !templateModuleKey.trim() ||
                !moduleImportEnabled
              }
            >
              {templateDownloading ? (
                <LoadingOutlined className="size-4 animate-spin" />
              ) : (
                <DownloadOutlined className="size-4" />
              )}
              DownloadOutlined
            </Button>
          </div>
          {templateError ? (
            <p className="mt-2 text-sm text-destructive">{templateError}</p>
          ) : null}
          <p className="mt-2 text-xs text-muted-foreground">
            Starter template for a module schema (genes). Format: TSV / CSV / XLSX.
            {" "}{xlsxImportState === "disabled" ? "XLSX is currently disabled by an administrator." : ""}
          </p>
        </div>

        {/* Stats */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label={t("admin.importPage.filteredTotal", { defaultValue: "Matching tasks" })} value={isError || !data ? "—" : stats.total} icon={<DatabaseOutlined className="size-5" />} />
          <StatCard
            label={t("admin.importPage.pageRunning", { defaultValue: "Running / queued on this page" })}
            value={isError || !data ? "—" : stats.running}
            icon={<LoadingOutlined className={cn("size-5", stats.running > 0 && "animate-spin")} />}
          />
          <StatCard label={t("admin.importPage.pageCompleted", { defaultValue: "Completed on this page" })} value={isError || !data ? "—" : stats.completed} icon={<CheckCircleOutlined className="size-5" />} />
          <StatCard label={t("admin.importPage.pageFailed", { defaultValue: "Failed on this page" })} value={isError || !data ? "—" : stats.failed} icon={<CloseCircleOutlined className="size-5" />} />
        </div>

        {resumeDraftId ? (
          <section aria-labelledby="resume-draft-heading" className="rounded-lg border border-primary/30 bg-primary/5 p-4">
            <Typography.Title id="resume-draft-heading" level={5} className="!mb-1">{t("admin.importPage.resumeDraft")}</Typography.Title>
            {resumeDraftQuery.isPending ? <Typography.Text type="secondary">{t("admin.importPage.loadingDraft")}</Typography.Text> : null}
            {resumeDraftQuery.isError ? <Typography.Text type="danger">{t("admin.importPage.draftUnavailable")}</Typography.Text> : null}
            {resumeDraftQuery.data ? (
              <div className="text-sm">
                <Typography.Text strong>{resumeDraftQuery.data.filename}</Typography.Text>
                <Typography.Text type="secondary" className="ml-2">{resumeDraftQuery.data.status} · {resumeDraftQuery.data.row_count} rows · {resumeDraftQuery.data.column_count} columns · {resumeDraftQuery.data.field_mapping.length} mapped fields</Typography.Text>
                <ImportDraftEditor
                  draft={resumeDraftQuery.data}
                  onUpdated={() => {
                    void resumeDraftQuery.refetch();
                    void draftsQuery.refetch();
                  }}
                />
              </div>
            ) : null}
          </section>
        ) : null}

        <section aria-labelledby="import-drafts-heading" className="rounded-lg border p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <Typography.Title id="import-drafts-heading" level={5} className="!mb-0">{t("admin.importPage.savedDrafts")}</Typography.Title>
              <Typography.Text type="secondary">{t("admin.importPage.savedDraftsHint")}</Typography.Text>
            </div>
            <Button size="small" onClick={() => draftsQuery.refetch()} loading={draftsQuery.isFetching}>{t("common.retry")}</Button>
          </div>
          {draftsQuery.isError ? <Typography.Text type="danger">{t("admin.importPage.savedDraftsUnavailable")}</Typography.Text> : null}
          {draftsQuery.data?.length ? (
            <ul className="mt-3 space-y-2" aria-label={t("admin.importPage.savedDrafts")}>
              {draftsQuery.data.map((draft) => (
                <li key={draft.id} className="flex items-center justify-between gap-3 rounded border p-2">
                  <div>
                    <Typography.Text strong>{draft.filename}</Typography.Text>
                    <Typography.Text type="secondary" className="ml-2 text-xs">{draft.status} · {draft.row_count} rows · {draft.column_count} columns</Typography.Text>
                  </div>
                  <Button size="small" href={`${import.meta.env.BASE_URL.replace(/\/$/, "")}/imports?draft=${encodeURIComponent(draft.id)}`}>{t("admin.importPage.resume")}</Button>
                </li>
              ))}
            </ul>
          ) : draftsQuery.isSuccess ? <Typography.Text type="secondary">{t("admin.importPage.noDrafts")}</Typography.Text> : null}
        </section>

        {/* Search */}
        <Input
          data-testid="imports-search"
          placeholder={t("admin.importPage.searchPlaceholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />

        {/* Table */}
        <div data-testid="imports-table" data-state={taskListState}>
        {isError ? (
          /* A failed request is not an empty task list. */
          <div
            role="alert"
            data-testid="imports-load-error"
            className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
          >
            {t("admin.importPage.loadError", { defaultValue: "The import tasks could not be loaded." })}
          </div>
        ) : isLoading ? <Skeleton active /> : (
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
        )}
        </div>

        {/* CloudUploadOutlined dialog */}
        <Modal open={showUpload} onCancel={closeUploadDialog}>
          <div>
            <div>
              <Typography.Title level={5}>{t("admin.importPage.newImport")}</Typography.Title>
              <Typography.Text type="secondary">
                CloudUploadOutlined a local file (browser-direct to object storage) or reference
                an already-uploaded S3 object.
              </Typography.Text>
            </div>

            <div className="space-y-4 py-2">
              {/* Import type */}
              <div className="space-y-1.5">
                <label htmlFor="import-type">{t("admin.importPage.importType")}</label>
                <Select
                  aria-label={t("admin.importPage.importType")}
                  value={uploadType}
                  onChange={(v) => setUploadType(v as ImportType)}
                  options={AVAILABLE_SUBMISSION_IMPORT_TYPES.map((type) => ({
                    value: type,
                    label: TYPE_LABELS[type],
                    disabled: !moduleImportEnabled,
                  }))}
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="import-data-set-id">{t("admin.importPage.datasetId")}</label>
                <Input
                  id="import-data-set-id"
                  type="number"
                  min="1"
                  inputMode="numeric"
                  placeholder={t("admin.importPage.datasetIdPlaceholder")}
                  value={uploadDataSetId}
                  onChange={(e) => setUploadDataSetId(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Required. This binds the import and its object key to one data set.
                </p>
              </div>

              {/* CloudUploadOutlined mode */}
              <div className="space-y-1.5">
                <label htmlFor="import-mode">{t("admin.importPage.source")}</label>
                <Select
                  value={effectiveUploadMode}
                  onChange={(v) => setUploadMode(v as "local" | "s3")}
                  options={[
                    { value: "local", label: t("admin.importPage.localFile"), disabled: !localUploadEnabled },
                    { value: "s3", label: t("admin.importPage.s3Uri") },
                  ]}
                />
              </div>

              {effectiveUploadMode === "local" ? (
                <div className="space-y-1.5">
                  <label>{t("admin.importPage.file")}</label>
                  <FileDropInput
                    file={uploadFile}
                    onSelect={(f) => {
                      setUploadFile(f);
                      setUploadFilename(f.name);
                      setUploadError(null);
                      invalidatePreview();
                    }}
                    accept=".txt,.tsv,.csv,.xlsx"
                  />
                  {uploadFile ? (
                    <p className="text-xs text-muted-foreground">
                      {uploadFile.name} · {formatBytes(uploadFile.size)}
                      {uploadType === "module_tsv" ? " · format " + extensionOf(uploadFile.name).toUpperCase() : ""}
                    </p>
                  ) : null}
                  {uploading ? (
                    <div className="space-y-1" role="progressbar" aria-valuenow={uploadProgress} aria-valuemin={0} aria-valuemax={100}>
                      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary transition-all"
                          style={{ width: `${uploadProgress}%` }}
                        />
                      </div>
                      <p className="text-xs text-muted-foreground">{t("admin.importPage.uploading")} {uploadProgress}%</p>
                    </div>
                  ) : null}
                </div>
              ) : (
                <>
                  {/* Filename */}
                  <div className="space-y-1.5">
                    <label htmlFor="import-filename">{t("admin.importPage.filename")}</label>
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
                    <label htmlFor="import-filepath">{t("admin.importPage.s3FilePath")}</label>
                    <Input
                      id="import-filepath"
                      placeholder={t("admin.importPage.s3FilePathPlaceholder")}
                      value={uploadFilePath}
                      onChange={(e) => setUploadFilePath(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      The S3 URI where the file has already been uploaded.
                    </p>
                  </div>
                </>
              )}

              {/* Module-specific fields */}
              {uploadType === "module_tsv" ? (
                <>
                  <div className="space-y-1.5">
                    <label htmlFor="import-release-id">{t("admin.importPage.releaseId")}</label>
                    <Input
                      id="import-release-id"
                      type="number"
                      min="1"
                      inputMode="numeric"
                      placeholder={t("admin.importPage.releaseIdPlaceholder")}
                      value={uploadReleaseId}
                      onChange={(e) => setUploadReleaseId(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Required. Module rows are immutable within one existing release.
                    </p>
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="import-module-key">{t("admin.importPage.moduleKey")}</label>
                    <Input
                      id="import-module-key"
                      placeholder={t("admin.importPage.moduleKeyPlaceholder")}
                      value={uploadModuleKey}
                      onChange={(e) => {
                        setUploadModuleKey(e.target.value);
                        invalidatePreview();
                      }}
                    />
                    <p className="text-xs text-muted-foreground">
                      Server-owned schema key. Supports .tsv / .txt / .csv / .xlsx.
                    </p>
                  </div>
                  {effectiveUploadMode === "s3" ? (
                    <div className="space-y-1.5">
                      <label htmlFor="import-checksum">{t("admin.importPage.checksum")}</label>
                      <Input
                        id="import-checksum"
                        placeholder={t("admin.importPage.checksumPlaceholder")}
                        value={uploadChecksum}
                        onChange={(e) => setUploadChecksum(e.target.value)}
                      />
                    </div>
                  ) : null}
                  <div className="space-y-1.5">
                    <Button
                      htmlType="button"
                      type="default"
                      size="small"
                      disabled={!uploadFile || uploadType !== "module_tsv"}
                      onClick={checkPreview}
                    >
                      {previewState?.status === "checking" ? (
                        <LoadingOutlined className="size-3.5 animate-spin" />
                      ) : null}
                      Preview
                    </Button>
                    {previewState?.status === "unavailable" ? (
                      <p className="text-xs text-muted-foreground">
                        {previewState.reason}
                      </p>
                    ) : null}
                    {previewState?.status === "available" ? (
                      <div className="space-y-2 rounded-md border border-border p-3">
                        <p className="text-xs text-muted-foreground">
                          Validated {previewState.rowCount} row{previewState.rowCount === 1 ? "" : "s"}
                          {previewState.truncated ? "; only the first 100 rows are shown." : "."}
                          {" "}This preview is read-only; edits are not included in the import.
                        </p>
                        {!previewState.validation.ok ? (
                          <p className="text-xs text-destructive">
                            {previewState.validation.errorCount} validation error{previewState.validation.errorCount === 1 ? "" : "s"}
                            {previewState.validation.errors[0]
                              ? `: ${previewState.validation.errors[0].message}`
                              : "."}
                          </p>
                        ) : null}
                        {previewState.rows.length > 0 && previewState.headers.length > 0 ? (
                          <ImportPreviewTable
                            ariaLabel="Validated module preview"
                            columns={previewState.headers}
                            rows={previewState.rows}
                            rowKey={(row, index) => `${index}:${String(row.gene_id ?? row.id ?? "row")}`}
                            editable={false}
                            height={240}
                          />
                        ) : (
                          <p className="text-xs text-muted-foreground">No valid preview rows were found.</p>
                        )}
                      </div>
                    ) : null}
                  </div>
                </>
              ) : null}

              {uploadError ? (
                <p className="text-sm text-destructive">{uploadError}</p>
              ) : null}
            </div>

            <div>
              <Button
                type="default"
                onClick={closeUploadDialog}
                disabled={submitMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                aria-label="Submit Import"
                onClick={handleUploadSubmit}
                disabled={
                  submitMutation.isPending ||
                  uploading ||
                  !capabilitiesQuery.isSuccess ||
                  (effectiveUploadMode === "local"
                    ? !uploadFile
                    : !uploadFilename.trim() || !uploadFilePath.trim())
                }
              >
                {submitMutation.isPending ? (
                  <>
                    <LoadingOutlined className="size-4 animate-spin" />
                    Submitting…
                  </>
                ) : (
                  <>
                    <CloudUploadOutlined className="size-4" />
                    Submit Import
                  </>
                )}
              </Button>
            </div>

            {submitMutation.isError ? (
              <p className="text-sm text-destructive">
                {submitMutation.error instanceof Error
                  ? submitMutation.error.message
                  : "Failed to submit import task."}
              </p>
            ) : null}
          </div>
        </Modal>

        {/* Cancel confirmation */}
        {cancelTarget && (
          <ConfirmDialog
            open={Boolean(cancelTarget)}
            onOpenChange={(open) => {
              if (!open) {
                setCancelTarget(null);
                setCancelError(null);
              }
            }}
            title={t("admin.importPage.cancelTaskTitle", { defaultValue: "Cancel import task" })}
            description={t("admin.importPage.cancelTaskConfirm", {
              defaultValue: 'Cancel the import task "{{filename}}"? A running task is stopped and cannot be resumed.',
              filename: cancelTarget.filename,
            })}
            confirmLabel={t("admin.importPage.cancelTaskConfirmLabel", { defaultValue: "Cancel task" })}
            severity="destructive"
            onConfirm={() => cancelMutation.mutate(cancelTarget.id)}
            loading={cancelMutation.isPending}
            error={cancelError ? (
              <span data-testid="imports-cancel-error">
                {t("admin.importPage.cancelFailed", { defaultValue: "The import task could not be cancelled." })}
                {" "}
                {t("common.errorReason", {
                  reason: cancelError,
                  defaultValue: "Server response: {{reason}}",
                })}
              </span>
            ) : null}
          />
        )}

        {/* Retry confirmation */}
        {retryTarget && (
          <ConfirmDialog
            open={Boolean(retryTarget)}
            onOpenChange={(open) => {
              if (!open) {
                setRetryTarget(null);
                setRetryError(null);
              }
            }}
            title={t("admin.importPage.retryTaskTitle", { defaultValue: "Retry import task" })}
            description={t("admin.importPage.retryTaskConfirm", {
              defaultValue: 'Retry the import task "{{filename}}"? A new task is submitted for the same file.',
              filename: retryTarget.filename,
            })}
            confirmLabel={t("common.retry", { defaultValue: "Retry" })}
            onConfirm={() => retryMutation.mutate(retryTarget.id)}
            loading={retryMutation.isPending}
            error={retryError ? (
              <span data-testid="imports-retry-error">
                {t("admin.importPage.retryFailed", { defaultValue: "The import task could not be retried." })}
                {" "}
                {t("common.errorReason", {
                  reason: retryError,
                  defaultValue: "Server response: {{reason}}",
                })}
              </span>
            ) : null}
          />
        )}
      </div>
    </PageContainer>
  );
}



interface FileDropInputProps {
  file: File | null;
  accept: string;
  onSelect: (file: File) => void;
}

function FileDropInput({ file, accept, onSelect }: FileDropInputProps) {
  return (
    <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed border-border p-4 text-sm hover:border-primary">
      <FileExcelOutlined className="size-5 text-primary" aria-hidden />
      <span className="min-w-0 flex-1 truncate">{file?.name ?? "Choose a local file"}</span>
      <input
        type="file"
        className="sr-only"
        accept={accept}
        onChange={(event) => {
          const selected = event.target.files?.[0];
          if (selected) onSelect(selected);
          event.currentTarget.value = "";
        }}
      />
      <span className="text-xs font-medium text-primary">Browse</span>
    </label>
  );
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function extensionOf(filename: string): string {
  const match = filename.toLowerCase().match(/\.[a-z0-9]+$/);
  return match?.[0] ?? "";
}
