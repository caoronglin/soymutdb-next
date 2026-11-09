import { useTranslation } from "react-i18next";
import { Link } from "@tanstack/react-router";
import { CloudUploadOutlined, FileExcelOutlined, DatabaseOutlined, RedoOutlined, CloseCircleOutlined, CheckCircleOutlined, LoadingOutlined, DownloadOutlined } from "@ant-design/icons";
import { Skeleton, Badge, Button, Input, PageContainer, Select, Typography, App } from "@/lib/antd";
import { StatCard } from "../components/stat-card";
import { ConfirmDialog } from "../components/confirm-dialog";
import { useState, useEffect, useCallback, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { http, authRequestBlob, capabilitiesApi, adminImportStudioApi, type ImportDraftListItemResponse, type ImportDraftResponse } from "@soymutdb/api-client";
import { cn } from "../lib/cn";
import { summarizeImportPage } from "../lib/import-task-stats";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { ImportDraftEditor } from "../components/import-draft-editor";
import { StatusBadge, type TaskStatus } from "../components/status-badge";
import { resolveFeatureState } from "../lib/capability-state";

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
 * continue to render correctly. New submissions expose only durable writers
 * and are handled by the standalone wizard at ``/imports/new``.
 */

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
  const { t } = useTranslation();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  // A resume link names a server-created draft; the submission wizard never
  // supplies or recreates this identifier.
  const resumeDraftId = typeof window === "undefined"
    ? null
    : new URLSearchParams(window.location.search).get("draft");

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");

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
  const moduleImportEnabled = moduleImportState === "enabled";
  const xlsxImportEnabled = xlsxImportState === "enabled";

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
        <Button key="new-import" type="primary" data-testid="imports-new" href={`${import.meta.env.BASE_URL.replace(/\/$/, "")}/imports/new`} disabled={!capabilitiesQuery.isSuccess} icon={<CloudUploadOutlined aria-hidden />} aria-label={t("admin.importPage.newImport")}>{t("admin.importPage.newImport")}</Button>,
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
                    <Typography.Text type="secondary" className="ml-2 text-xs">
                      {t("admin.importPage.draftCounts", {
                        defaultValue: "{{rows}} rows · {{columns}} columns",
                        rows: draft.row_count,
                        columns: draft.column_count,
                      })}
                    </Typography.Text>
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
          aria-label={t("admin.importPage.searchPlaceholder")}
          placeholder={t("admin.importPage.searchPlaceholder")}
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
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
            emptyTitle={t("admin.importPage.emptyTitle", { defaultValue: "No import tasks" })}
            emptyDescription={t("admin.importPage.emptyDescription", { defaultValue: "Submit a new import to get started." })}
          />
        )}
        </div>

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
